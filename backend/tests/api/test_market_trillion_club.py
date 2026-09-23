from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.market import get_market_provider, get_option_provider
from app.db import get_session
from app.db_models import Base
from app.domain.indicators import DailyBar
from app.main import app
from app.market.base import (
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
        if symbol != "AAPL":
            raise MarketDataError(f"{symbol} market cap unavailable")
        return MarketCapitalization(
            symbol=symbol,
            value=Decimal("4200000000000"),
            currency="USD",
            as_of=date(2026, 6, 30),
            source="yahoo",
        )

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
        assert apple["market_cap"] == 4_200_000_000_000.0
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
