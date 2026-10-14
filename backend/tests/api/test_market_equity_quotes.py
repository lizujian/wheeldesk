from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.market import get_market_provider, get_vix_provider
from app.db import get_session
from app.db_models import Base
from app.domain.indicators import DailyBar
from app.main import app
from app.market.base import MarketDataError, MarketSeries, SessionQuote


class EquityProvider:
    def __init__(self) -> None:
        self.fail_symbols: set[str] = {"BAD"}

    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries:
        if symbol in self.fail_symbols:
            raise MarketDataError(f"{symbol} unavailable")
        prices = {"QQQ": "500", "TQQQ": "80", "BRK.B": "510", "VOO": "600", "SCHD": "33", "VIX": "18", "AAPL": "220", "QLD": "90"}
        if symbol not in prices:
            raise MarketDataError(f"{symbol} unavailable")
        close = Decimal(prices[symbol])
        start = date(2025, 9, 26)
        bars = [
            DailyBar(
                date=start + timedelta(days=index),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
            )
            for index in range(300)
        ]
        return MarketSeries(symbol=symbol, bars=bars[-limit:], source="yahoo")


@contextmanager
def quote_client(provider: EquityProvider):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    Base.metadata.create_all(engine)

    def override_session():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_market_provider] = lambda: provider
    app.dependency_overrides[get_vix_provider] = app.dependency_overrides[get_market_provider]
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def initialize(client: TestClient) -> None:
    client.post(
        "/api/portfolio/initialize",
        json={
            "age": 36,
            "opening_equity": 100000,
            "opening_date": "2026-07-22",
        },
    )


def test_vix_context_serializes_snapshot_and_history_without_changing_strategy_close():
    class VixProvider(EquityProvider):
        history_failed = False

        def session_quote(self, symbol):
            if symbol != 'VIX':
                raise MarketDataError('snapshot unavailable')
            now = datetime.now(timezone.utc)
            return SessionQuote('VIX', Decimal(12), Decimal(18), now, date.today(), 'regular', 'ibkr', 'delayed', now)

        def daily_bars(self, symbol, limit=300):
            if symbol != 'VIX':
                return super().daily_bars(symbol, limit)
            return MarketSeries('VIX', [DailyBar(date.today()-timedelta(days=i), Decimal(18), Decimal(25), Decimal(10), Decimal(18), 0)
                for i in range(400, 0, -1)][-limit:], 'ibkr')

        def vix_history(self):
            if self.history_failed:
                raise MarketDataError('VIX history unavailable')
            return self.daily_bars('VIX', 400)

    provider = VixProvider()
    with quote_client(provider) as client:
        initialize(client)
        for failed in [False, True]:
            provider.history_failed = failed
            response = client.post('/api/market/refresh')
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload['market']['vix']['price'] == 18
            assert payload['vix_context']['price'] == 12
            assert payload['vix_context']['price_kind'] == 'snapshot'
            if failed:
                assert payload['vix_context']['percentile_fraction'] is None
                assert payload['vix_context']['history_error'] == 'VIX history unavailable'
            else:
                assert payload['vix_context']['percentile_fraction'] == 0
                assert payload['vix_context']['high_52w'] == 25
                assert payload['vix_context']['sample_size'] == 364


def test_refresh_updates_each_public_equity_without_failing_the_batch() -> None:
    provider = EquityProvider()
    with quote_client(provider) as client:
        initialize(client)
        core = client.post(
            "/api/positions",
            json={
                "bucket": "core",
                "symbol": "BRK.B",
                "asset_type": "equity",
                "quantity": 2,
                "entry_price": 480,
                "opened_on": "2026-07-01",
            },
        )
        assert core.status_code == 201
        client.post("/api/other-holdings", json={"symbol": "AAPL", "quantity": 10})
        client.post("/api/other-holdings", json={"symbol": "BAD", "quantity": 3})

        refreshed = client.post("/api/market/refresh")

        assert refreshed.status_code == 200
        payload = refreshed.json()
        assert payload["equities"]["AAPL"]["price"] == 220.0
        assert payload["equities"]["AAPL"]["status"] == "updated"
        assert payload["equities"]["BAD"]["price"] is None
        assert payload["equities"]["BAD"]["status"] == "unavailable"
        assert payload["market"]["voo"]["price"] == 600.0
        assert payload["core"]["mode"] == "accumulating"
        assert payload["core"]["selected_symbol"] in {"BRK.B", "VOO"}
        assert payload["core"]["recommendation"]["symbol"] in {"BRK.B", "VOO"}
        assert payload["core"]["recommendation"]["cash_required"] == 0.0
        assert payload["core"]["recommendation"]["daily_change"] == 0.0
        assert payload["core"]["recommendation"]["signal_score"] == 0
        assert payload["core"]["recommendation"]["trend_reduced"] is False

        positions = client.get("/api/positions").json()
        assert positions[0]["current_price"] == 510.0
        listing = client.get("/api/other-holdings").json()
        aapl = next(record for record in listing["records"] if record["symbol"] == "AAPL")
        bad = next(record for record in listing["records"] if record["symbol"] == "BAD")
        assert aapl["current_value"] == 2200.0
        assert bad["current_value"] is None


def test_refresh_preserves_the_last_good_quote_after_a_later_failure() -> None:
    provider = EquityProvider()
    with quote_client(provider) as client:
        initialize(client)
        client.post("/api/other-holdings", json={"symbol": "AAPL", "quantity": 4})
        assert client.post("/api/market/refresh").status_code == 200

        provider.fail_symbols.add("AAPL")
        second = client.post("/api/market/refresh")

        assert second.status_code == 200
        assert second.json()["equities"]["AAPL"]["price"] == 220.0
        assert second.json()["equities"]["AAPL"]["status"] == "stale"
        record = client.get("/api/other-holdings").json()["records"][0]
        assert record["current_price"] == 220.0
        assert record["quote_status"] == "stale"


def test_refresh_updates_qld_equity_inside_the_leaps_bucket() -> None:
    provider = EquityProvider()
    with quote_client(provider) as client:
        initialize(client)
        opened = client.post(
            "/api/positions",
            json={
                "bucket": "leaps",
                "symbol": "QLD",
                "asset_type": "equity",
                "direction": "long",
                "quantity": 100,
                "entry_price": 80,
                "opened_on": "2026-07-22",
                "tranche": 1,
            },
        )
        assert opened.status_code == 201, opened.text

        refreshed = client.post("/api/market/refresh")

        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["equities"]["QLD"]["price"] == 90.0
        position = client.get("/api/positions").json()[0]
        assert position["current_price"] == 90.0
        assert position["current_value"] == 9000.0
        assert position["exit_decision"]["code"] == "hold"

        provider.fail_symbols.add("QLD")
        failed = client.post("/api/market/refresh")

        assert failed.status_code == 200, failed.text
        assert failed.json()["equities"]["QLD"]["status"] == "stale"
        assert failed.json()["equities"]["QLD"]["price"] == 90.0
        preserved = client.get("/api/positions").json()[0]
        assert preserved["current_price"] == 90.0
        assert preserved["current_value"] == 9000.0
