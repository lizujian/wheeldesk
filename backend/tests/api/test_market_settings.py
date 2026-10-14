from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.market import get_market_provider, get_option_provider, get_vix_provider
from app.db import get_session
from app.db_models import Base, LedgerEvent, MarketDataSettings, SignalRecord, UnmanagedPositionRecord
from app.main import app
from app.market.base import MarketDataError, SessionQuote
from app.market.factory import close_providers, market_provider
from app.market.settings import MarketSettings
from app.market.sample import SampleMarketDataProvider


@pytest.fixture
def local_client():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def session_dependency():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session] = session_dependency
    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()
        close_providers()
        engine.dispose()


def test_unconfigured_gateway_reports_setup_instead_of_using_another_source(local_client):
    client, _ = local_client
    settings = client.get("/api/settings/market").json()
    assert settings["provider"] == settings["effective_provider"] == "ibkr"
    assert settings["vix_provider"] == "ibkr" and not settings["configured"]
    assert client.post("/api/market/refresh").status_code == 503
    with pytest.raises(MarketDataError, match="配置 IB Gateway"):
        market_provider(MarketSettings())
    assert client.put("/api/settings/market", json={"provider": "yahoo"}).status_code == 422


def test_settings_persist_connection_without_account_secrets(local_client):
    client, engine = local_client
    payload = {"provider": "ibkr", "ibkr_host": "127.0.0.1", "ibkr_port": 4001}
    saved = client.put("/api/settings/market", json=payload)
    assert saved.status_code == 200
    assert saved.json()["effective_provider"] == "ibkr"
    assert saved.json()["vix_provider"] == "ibkr"
    assert client.get("/api/settings/market").json() == saved.json()
    with Session(engine) as session:
        assert session.get(MarketDataSettings, 1).ibkr_port == 4001
    assert client.put("/api/settings/market", json={**payload, "password": "secret"}).status_code == 422
    for invalid in [{"ibkr_host": "http://localhost"}, {"ibkr_port": 0}, {"ibkr_port": 65536}, {"ibkr_client_id": 0}]:
        assert client.put("/api/settings/market", json={**payload, **invalid}).status_code == 422


def test_switch_keeps_valuation_provenance_and_ledger_but_retires_old_advice(local_client):
    client, engine = local_client
    with Session(engine) as session:
        session.add(UnmanagedPositionRecord(category="other", symbol="AVGO", asset_type="equity", direction="long",
                    quantity=100, multiplier=1, current_price=Decimal(390), quote_source="yahoo"))
        session.add(SignalRecord(code="leaps_entry_opportunity", title="old", message="old", severity="opportunity", market_date=date.today()))
        session.add(LedgerEvent(event_type="test", bucket="core", amount=Decimal(1), occurred_on=date.today(), details={}))
        session.commit()
    client.put("/api/settings/market", json={"provider": "ibkr", "ibkr_host": "127.0.0.1", "ibkr_port": 4001})
    with Session(engine) as session:
        record = session.scalar(select(UnmanagedPositionRecord))
        assert record.current_price == 390 and record.quantity == 100
        assert record.quote_source == "yahoo" and record.quote_quality == "stale"
        assert session.scalar(select(SignalRecord)).acknowledged
        assert len(list(session.scalars(select(LedgerEvent)))) == 1


def test_test_connection_neither_saves_settings_nor_exposes_credentials(local_client, monkeypatch):
    client, _ = local_client
    from app.api import market_settings
    monkeypatch.setattr(market_settings.IbkrMarketDataProvider, "diagnostics", lambda _: (_ for _ in ()).throw(MarketDataError("无法连接 IB Gateway")))
    response = client.post("/api/settings/market/test", json={"ibkr_host": "127.0.0.1", "ibkr_port": 4001})
    assert response.status_code == 200 and not response.json()["connected"]
    assert client.get("/api/settings/market").json()["configured"] is False


class PrimaryProvider(SampleMarketDataProvider):
    def daily_bars(self, symbol, limit=300):
        return replace(super().daily_bars(symbol, limit), source="ibkr")

    def session_quote(self, symbol):
        return SessionQuote(symbol, Decimal(390), Decimal(380), datetime.now(timezone.utc), date.today(), "regular", "ibkr", "realtime")


class VixFailure:
    def daily_bars(self, symbol, limit=300):
        assert symbol == "VIX"
        raise MarketDataError("IBKR VIX unavailable")


def test_vix_failure_preserves_stock_refresh_and_suppresses_vix_dependent_signals(local_client):
    client, engine = local_client
    primary = PrimaryProvider(as_of=date.today())
    app.dependency_overrides[get_market_provider] = lambda: primary
    app.dependency_overrides[get_option_provider] = lambda: primary
    app.dependency_overrides[get_vix_provider] = lambda: VixFailure()
    client.post("/api/portfolio/initialize", json={"age": 36, "opening_equity": 100000, "opening_date": date.today().isoformat()})
    client.post("/api/other-holdings", json={"symbol": "AVGO", "quantity": 100})
    with Session(engine) as session:
        session.add(SignalRecord(code="vix_high", title="old", message="old", severity="warning", market_date=date.today()))
        session.commit()
    refreshed = client.post("/api/market/refresh")
    assert refreshed.status_code == 200, refreshed.text
    value = refreshed.json()
    assert value["equities"]["AVGO"]["price"] == 390
    assert value["market"]["vix"]["price"] is None
    assert value["market"]["vix"]["source"] == "ibkr"
    assert value["errors"][0]["symbol"] == "VIX"
    assert all(not asset["actionable"] for asset in value["core"]["assets"])
    assert not value["core"]["sell_put"]["actionable"]
    with Session(engine) as session:
        assert session.scalar(select(SignalRecord).where(SignalRecord.code == "vix_high")).acknowledged


def test_vix_uses_selected_provider_and_records_actual_source(local_client):
    client, _ = local_client
    primary = PrimaryProvider(as_of=date.today())
    app.dependency_overrides[get_market_provider] = lambda: primary
    app.dependency_overrides[get_option_provider] = lambda: primary
    client.post("/api/portfolio/initialize", json={"age": 36, "opening_equity": 100000, "opening_date": date.today().isoformat()})
    value = client.post("/api/market/refresh").json()
    assert value["market"]["vix"]["price"] is not None
    assert value["market"]["vix"]["source"] == value["vix_provider"] == "ibkr"


def test_manual_watchlist_persists_normalizes_and_controls_new_leaps_members(local_client):
    client, _ = local_client
    settings = {"ibkr_host": "127.0.0.1", "ibkr_port": 4001, "club_symbols": [" avgo ", "AVGO", "amd", "BRK.B"]}
    saved = client.put("/api/settings/market", json=settings)
    assert saved.status_code == 200, saved.text
    assert saved.json()["club_symbols"] == ["AVGO", "AMD", "BRK-B"]
    assert client.get("/api/settings/market").json()["club_symbols"] == ["AVGO", "AMD", "BRK-B"]
    for symbols in [["invalid$"], ["QQQ"]]:
        assert client.put("/api/settings/market", json={**settings, "club_symbols": symbols}).status_code == 422
    payload = {"bucket": "leaps", "symbol": "AMD", "asset_type": "option", "direction": "long", "option_type": "call", "quantity": 1, "entry_price": 20, "opened_on": "2026-10-14", "expiration": "2027-10-15", "strike": 100, "tranche": 1}
    added = client.post("/api/positions", json=payload)
    assert added.status_code == 201, added.text
    assert added.json()["leaps_category"] == "club"
    assert client.post("/api/positions", json={**payload, "symbol": "AAPL"}).status_code == 422
    client.put("/api/settings/market", json={**settings, "club_symbols": []})
    assert client.get("/api/positions").json()[0]["leaps_category"] == "club"


def test_refresh_only_loads_manual_members_and_never_queries_market_cap_or_earnings(local_client):
    client, _ = local_client
    class ManualProvider(PrimaryProvider):
        def market_cap(self, symbol):
            raise AssertionError("Market cap must not be requested")
        def earnings_date(self, symbol):
            raise AssertionError("Earnings must not be requested")
    primary = ManualProvider(as_of=date.today())
    app.dependency_overrides[get_market_provider] = lambda: primary
    app.dependency_overrides[get_option_provider] = lambda: primary
    client.post("/api/portfolio/initialize", json={"age": 36, "opening_equity": 100000, "opening_date": date.today().isoformat()})
    configured = client.put("/api/settings/market", json={"club_symbols": ["AMD"]}).json()
    value = client.post("/api/market/refresh").json()
    assert [row["symbol"] for row in value["leaps_club"]["decisions"]] == ["AMD"]
    assert value["leaps_club"]["unavailable"] == []
    emptied = client.put("/api/settings/market", json={"club_symbols": []}).json()
    assert emptied["config_key"] != configured["config_key"]
    assert client.post("/api/market/refresh").json()["leaps_club"]["decisions"] == []
