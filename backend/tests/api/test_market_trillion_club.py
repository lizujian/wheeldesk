from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.market import get_market_provider, get_option_provider, get_vix_provider
from app.db import get_session
from app.db_models import Base
from app.domain.indicators import DailyBar
from app.main import app
from app.market.base import (
    ImpliedVolatilityComparison,
    ImpliedVolatilityPoint,
    MarketCapitalization,
    MarketDataError,
    MarketSeries,
    SessionQuote,
)


class ClubProvider:
    market_date = date(2026, 8, 17)
    aapl_price = Decimal("94")

    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries:
        if symbol not in {"QQQ", "TQQQ", "BRK.B", "VOO", "SCHD", "VIX", "AAPL"}:
            raise MarketDataError(f"{symbol} unavailable")
        if symbol == "AAPL":
            closes = [Decimal("80")] * 269
            closes += [Decimal("130")]
            closes += [Decimal(value) for value in range(129, 99, -1)]
        else:
            base = Decimal("18") if symbol == "VIX" else Decimal("100")
            closes = [base + Decimal(index) / Decimal("100") for index in range(300)]
        start = self.market_date - timedelta(days=299)
        bars = [
            DailyBar(
                date=start + timedelta(days=index),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
            )
            for index, close in enumerate(closes)
        ]
        return MarketSeries(symbol=symbol, bars=bars[-limit:], source="yahoo")

    def session_quote(self, symbol: str) -> SessionQuote:
        price = self.aapl_price if symbol == "AAPL" else Decimal("102.99")
        previous = Decimal("100") if symbol == "AAPL" else Decimal("102.99")
        return SessionQuote(
            symbol=symbol,
            price=price,
            previous_close=previous,
            quoted_at=datetime.combine(self.market_date, datetime.min.time(), timezone.utc),
            market_date=self.market_date,
            session="post",
            source="yahoo",
        )

    def market_cap(self, symbol: str) -> MarketCapitalization:
        raise AssertionError("Manual membership must never query market cap")

    def earnings_date(self, symbol):
        raise AssertionError("Earnings checks are disabled")

    def option_quote(self, symbol, option_type, expiration, strike):
        raise MarketDataError("option quote unavailable")


@contextmanager
def club_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    Base.metadata.create_all(engine)
    provider = ClubProvider()

    def override_session():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_market_provider] = lambda: provider
    app.dependency_overrides[get_vix_provider] = app.dependency_overrides[get_market_provider]
    app.dependency_overrides[get_option_provider] = lambda: provider
    try:
        yield TestClient(app), provider
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_refresh_returns_a_public_club_signal_and_uses_a_shared_leaps_budget() -> None:
    with club_client() as (client, provider):
        client.post(
            "/api/portfolio/initialize",
            json={"age": 36, "opening_equity": 100000, "opening_date": "2026-08-01"},
        )

        first = client.post("/api/market/refresh")

        assert first.status_code == 200, first.text
        payload = first.json()
        apple = next(row for row in payload["leaps_club"]["decisions"] if row["symbol"] == "AAPL")
        assert apple["technical_eligible"] is True
        assert apple["eligible"] is True
        assert apple["suggested_slot"] == 1
        assert apple["suggested_amount"] == 1500.0
        assert apple["market_cap"] is None
        assert apple["checks"]["club_member"] is True
        assert "market_cap" not in apple["checks"]
        assert "MU" in payload["leaps_club"]["exclusions"]
        assert all(row["symbol"] != "GOOGL" for row in payload["leaps_club"]["decisions"])
        wheel_apple = next(row for row in payload["wheel_club"]["decisions"] if row["symbol"] == "AAPL")
        assert wheel_apple["dte_range"] == [30, 45]
        assert wheel_apple["delta_range"] == [0.15, 0.25]
        assert wheel_apple["minimum_annualized_return"] == 0.12
        assert all(row["symbol"] != "BRK-B" for row in payload["wheel_club"]["decisions"])

        opened = client.post(
            "/api/positions",
            json={
                "bucket": "leaps",
                "symbol": "AAPL",
                "asset_type": "option",
                "direction": "long",
                "option_type": "call",
                "quantity": 1,
                "entry_price": 30,
                "opened_on": "2026-08-17",
                "expiration": "2027-08-13",
                "strike": 80,
                "tranche": 1,
                "underlying_entry_price": 100,
            },
        )
        assert opened.status_code == 201, opened.text

        same_week = client.post("/api/market/refresh").json()
        apple = next(row for row in same_week["leaps_club"]["decisions"] if row["symbol"] == "AAPL")
        assert apple["checks"]["weekly_limit"] is False

        provider.market_date = date(2026, 8, 24)
        provider.aapl_price = Decimal("91")
        next_week = client.post("/api/market/refresh").json()
        apple = next(row for row in next_week["leaps_club"]["decisions"] if row["symbol"] == "AAPL")
        assert apple["checks"]["weekly_limit"] is True
        assert apple["checks"]["second_entry"] is True
        assert apple["suggested_slot"] == 2


def test_sector_etfs_reuse_club_entry_rules_budget_and_weekly_frequency_without_manual_membership():
    with club_client() as (client, provider):
        client.post('/api/portfolio/initialize', json={'age': 36, 'opening_equity': 100000, 'opening_date': '2026-08-01'})
        client.put('/api/settings/market', json={'club_symbols': ['AAPL']})
        original_bars, original_quote = provider.daily_bars, provider.session_quote
        provider.daily_bars = lambda symbol, limit=300: replace(original_bars('AAPL' if symbol in {'DRAM', 'SOXX'} else symbol, limit), symbol=symbol)
        provider.session_quote = lambda symbol: replace(original_quote('AAPL' if symbol in {'DRAM', 'SOXX'} else symbol), symbol=symbol)
        payload = client.post('/api/market/refresh').json()
        apple = payload['leaps_club']['decisions'][0]
        assert len(payload['leaps_etfs']['decisions']) == 2
        for row in payload['leaps_etfs']['decisions']:
            assert row['checks'] == apple['checks']
            assert row['eligible'] and row['suggested_amount'] == 1500
        assert all(row['symbol'] not in {'DRAM', 'SOXX'} for row in payload['wheel_club']['decisions'])
        opened = client.post('/api/positions', json={'bucket': 'leaps', 'symbol': 'DRAM', 'asset_type': 'option',
            'direction': 'long', 'option_type': 'call', 'quantity': 1, 'entry_price': 10.68, 'opened_on': '2026-08-17',
            'expiration': '2027-06-17', 'strike': 50, 'tranche': 1})
        assert opened.status_code == 201, opened.text
        payload = client.post('/api/market/refresh').json()
        for row in [*payload['leaps_etfs']['decisions'], *payload['leaps_club']['decisions']]:
            assert not row['checks']['weekly_limit'] and not row['eligible']
        assert payload['pmcc']['individual']['committed'] == 1068


def test_short_dram_history_still_returns_real_rsi_but_blocks_the_same_club_signal_rules():
    with club_client() as (client, provider):
        client.post('/api/portfolio/initialize', json={'age': 36, 'opening_equity': 100000, 'opening_date': '2026-08-01'})
        original_bars, original_quote = provider.daily_bars, provider.session_quote
        provider.watchlist_bars = lambda symbol, limit=300: replace(original_bars('AAPL', 134 if symbol == 'DRAM' else limit), symbol=symbol)
        provider.session_quote = lambda symbol: replace(original_quote('AAPL' if symbol in {'DRAM', 'SOXX'} else symbol), symbol=symbol)
        response = client.post('/api/market/refresh')
        assert response.status_code == 200, response.text
        dram = next(row for row in response.json()['leaps_etfs']['decisions'] if row['symbol'] == 'DRAM')
        assert dram['ma200'] is None and dram['rsi14'] is not None
        assert not dram['checks']['stock_above_ma200'] and not dram['checks']['history']
        assert not dram['technical_eligible'] and not dram['eligible']


def test_refresh_serializes_watchlist_iv_and_isolates_missing_iv() -> None:
    with club_client() as (client, provider):
        client.post(
            "/api/portfolio/initialize",
            json={"age": 36, "opening_equity": 100000, "opening_date": "2026-08-01"},
        )
        saved = client.put("/api/settings/market", json={"club_symbols": ["AAPL"]})
        assert saved.status_code == 200, saved.text

        def implied_volatility(symbol):
            if symbol == "AAPL":
                raise MarketDataError("AAPL IV unavailable")
            return ImpliedVolatilityComparison(
                symbol,
                ImpliedVolatilityPoint(date(2026, 8, 17), Decimal(".25")),
                ImpliedVolatilityPoint(date(2026, 8, 14), Decimal(".2")),
                Decimal(".25"), "ibkr", datetime(2026, 8, 17, 20, tzinfo=timezone.utc),
            )

        provider.implied_volatility = implied_volatility
        refreshed = client.post("/api/market/refresh")
        assert refreshed.status_code == 200, refreshed.text
        rows = refreshed.json()["leaps_watchlist"]
        assert [row["symbol"] for row in rows] == ["QQQ", "DRAM", "SOXX", "AAPL"]
        assert rows[0]["iv"]["latest"] == {"as_of": "2026-08-17", "value": .25}
        assert rows[0]["iv"]["previous"] == {"as_of": "2026-08-14", "value": .2}
        assert rows[0]["iv"]["change_fraction"] == .25
        assert rows[0]["iv"]["source"] == "ibkr"
        assert rows[-1]["price"] == 94 and rows[-1]["rsi14"] is not None
        assert rows[-1]["iv"] is None and rows[-1]["iv_error"] == "AAPL IV unavailable"


def test_wheel_quote_age_uses_current_session_date_not_last_completed_bar() -> None:
    with club_client() as (client, provider):
        initialized = client.post(
            "/api/portfolio/initialize",
            json={"age": 36, "opening_equity": 100000, "opening_date": "2026-08-01"},
        )
        assert initialized.status_code == 201, initialized.text
        opened = client.post(
            "/api/wheel/portfolio/puts",
            json={
                "batch_number": 1,
                "trade_date": "2026-08-16",
                "expiration": "2026-09-25",
                "strike": 100,
                "premium": 5,
                "quantity": 1,
                "entry_tqqq_price": 103,
            },
        )
        assert opened.status_code == 201, opened.text

        refreshed = client.post("/api/market/refresh")

        assert refreshed.status_code == 200, refreshed.text
        overview = client.get("/api/wheel/overview").json()
        put = overview["rounds"][0]["puts"][0]
        assert put["early_close_days"] == 1
        assert put["early_close_return_kind"] == "estimated"
        assert put["early_close_annualized_return"] is not None


def test_confirmed_club_wheel_put_consumes_weekly_limit_and_symbol_cycle() -> None:
    with club_client() as (client, provider):
        initialized = client.post(
            "/api/portfolio/initialize",
            json={"age": 36, "opening_equity": 100000, "opening_date": "2026-08-01"},
        )
        assert initialized.status_code == 201, initialized.text
        opened = client.post(
            "/api/wheel/portfolio/puts",
            json={
                "symbol": "AAPL",
                "batch_number": 1,
                "trade_date": "2026-08-17",
                "expiration": "2026-09-25",
                "strike": 80,
                "premium": 2,
                "quantity": 1,
                "entry_tqqq_price": 94,
                "earnings_confirmed": True,
            },
        )
        assert opened.status_code == 201, opened.text

        refreshed = client.post("/api/market/refresh")

        assert refreshed.status_code == 200, refreshed.text
        apple = next(
            row for row in refreshed.json()["wheel_club"]["decisions"]
            if row["symbol"] == "AAPL"
        )
        assert apple["checks"]["weekly_limit"] is False
        assert apple["checks"]["no_active_cycle"] is False
        assert apple["active_cycle"] is True
