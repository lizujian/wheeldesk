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
from app.market.base import MarketSeries, OptionQuote


class LeapsQuoteProvider:
    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries:
        close = Decimal("500") if symbol in {"QQQ", "BRK.B"} else Decimal("80")
        if symbol == "VIX":
            close = Decimal("18")
        bars = [
            DailyBar(
                date=date(2025, 9, 26) + timedelta(days=index),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1_000_000,
            )
            for index in range(300)
        ]
        return MarketSeries(symbol=symbol, bars=bars[-limit:], source="yahoo")

    def option_quote(self, symbol, option_type, expiration, strike) -> OptionQuote:
        return OptionQuote(
            contract_symbol="QQQ270722C00400000",
            symbol="QQQ",
            option_type="call",
            expiration=expiration,
            strike=strike,
            bid=Decimal("200"),
            ask=Decimal("205"),
            last=Decimal("202"),
            implied_volatility=Decimal("0.25"),
            quoted_at=datetime(2026, 7, 22, 20, tzinfo=timezone.utc),
            source="yahoo",
        )


@contextmanager
def quote_client():
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

    provider = LeapsQuoteProvider()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_market_provider] = lambda: provider
    app.dependency_overrides[get_option_provider] = lambda: provider
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_refresh_marks_leaps_at_bid_and_serializes_the_exit_decision() -> None:
    with quote_client() as client:
        client.post(
            "/api/portfolio/initialize",
            json={
                "age": 36,
                "opening_equity": 100000,
                "opening_date": "2026-07-22",
            },
        )
        opened = client.post(
            "/api/positions",
            json={
                "bucket": "leaps",
                "symbol": "QQQ",
                "asset_type": "option",
                "direction": "long",
                "option_type": "call",
                "quantity": 1,
                "entry_price": 100,
                "opened_on": "2026-07-22",
                "expiration": "2027-07-22",
                "strike": 400,
                "tranche": 1,
            },
        )
        assert opened.status_code == 201, opened.text

        refreshed = client.post("/api/market/refresh")

        assert refreshed.status_code == 200
        position = client.get("/api/positions").json()[0]
        assert position["quote_bid"] == 200.0
        assert position["quote_source"] == "yahoo"
        assert position["current_value"] == 20000.0
        assert position["exit_decision"]["code"] == "take_profit"
        assert position["exit_decision"]["target_return"] == 0.5
