from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.market import get_market_provider, get_option_provider
from app.db import get_session
from app.db_models import Base, BucketBalance
from app.domain.indicators import DailyBar
from app.main import app
from app.market.base import MarketDataError, MarketSeries


class TwoDayBreakProvider:
    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries:
        start = date(2025, 9, 21)
        bars = []
        for index in range(300):
            close = Decimal("50") if index >= 298 else Decimal("100")
            bars.append(
                DailyBar(
                    date=start + timedelta(days=index),
                    open=close + Decimal("1"),
                    high=close + Decimal("2"),
                    low=close - Decimal("2"),
                    close=close,
                    volume=1_000_000,
                )
            )
        return MarketSeries(symbol=symbol, bars=bars, source="sample")

    def option_quote(self, symbol, option_type, expiration, strike):
        raise MarketDataError("no option quote")


@contextmanager
def risk_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(engine, expire_on_commit=False, class_=Session)
    with testing_session() as session:
        session.add(BucketBalance(bucket="wheel", amount=Decimal("100000")))
        session.commit()

    def override_session():
        with testing_session() as session:
            yield session

    provider = TwoDayBreakProvider()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_market_provider] = lambda: provider
    app.dependency_overrides[get_option_provider] = lambda: provider
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_new_wheel_put_triggers_critical_risk_after_two_day_ma200_break() -> None:
    with risk_client() as client:
        opened = client.post(
            "/api/wheel/portfolio/puts",
            json={
                "batch_number": 1,
                "trade_date": "2026-07-01",
                "expiration": "2026-08-21",
                "strike": 40,
                "premium": 1,
                "quantity": 1,
                "entry_tqqq_price": 50,
            },
        )
        assert opened.status_code == 201

        refreshed = client.post("/api/market/refresh")

        assert refreshed.status_code == 200
        assert refreshed.json()["risk"]["severity"] == "critical"
        assert refreshed.json()["risk"]["stop_required"] is True
