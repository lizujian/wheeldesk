from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.market import get_market_provider
from app.db import get_session
from app.db_models import Base
from app.domain.indicators import DailyBar
from app.main import app
from app.market.base import MarketSeries, SessionQuote


class LeapsEntryProvider:
    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries:
        closes = [Decimal("80")] * 269
        closes += [Decimal("130")]
        closes += [Decimal(value) for value in range(129, 99, -1)]
        bars = [
            DailyBar(
                date=date(2025, 9, 22) + timedelta(days=index),
                open=close - Decimal("0.5"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=1_000_000,
            )
            for index, close in enumerate(closes)
        ]
        return MarketSeries(symbol=symbol, bars=bars, source="yahoo")

    def session_quote(self, symbol: str) -> SessionQuote:
        return SessionQuote(
            symbol=symbol,
            price=Decimal("99"),
            previous_close=Decimal("101"),
            quoted_at=datetime(2026, 7, 18, 14, tzinfo=timezone.utc),
            market_date=date(2026, 7, 18),
            session="regular",
            source="yahoo",
        )


@contextmanager
def market_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(engine, expire_on_commit=False, class_=Session)

    def override_session():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_market_provider] = lambda: LeapsEntryProvider()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_funded_leaps_bucket_does_not_count_as_an_open_leaps_position() -> None:
    with market_client() as client:
        initialized = client.post(
            "/api/portfolio/initialize",
            json={
                "age": 30,
                "opening_equity": 100000,
                "opening_date": "2026-07-01",
            },
        )
        assert initialized.status_code == 201

        refreshed = client.post("/api/market/refresh")

        assert refreshed.status_code == 200
        payload = refreshed.json()
        assert len(payload["leaps"]) == 5
        assert payload["leaps_session"]["price"] == 99.0
        assert payload["leaps_session"]["change_fraction"] < -0.01
        first = payload["leaps"][0]
        assert first["eligible"] is True, first
        assert first["suggested_amount"] == 2000.0
        assert first["checks"]["above_ma200"] is True
        assert first["checks"]["rsi_below_45"] is True
        assert first["checks"]["daily_drop"] is True


def test_refresh_returns_the_oldest_position_as_fifo_candidate_when_five_slots_are_full() -> None:
    with market_client() as client:
        initialized = client.post(
            "/api/portfolio/initialize",
            json={
                "age": 30,
                "opening_equity": 100000,
                "opening_date": "2026-07-01",
            },
        )
        assert initialized.status_code == 201
        position_ids = []
        for slot in range(1, 6):
            opened = client.post(
                "/api/positions",
                json={
                    "bucket": "leaps",
                    "symbol": "QLD",
                    "asset_type": "equity",
                    "direction": "long",
                    "quantity": 1,
                    "entry_price": 100,
                    "opened_on": f"2026-07-{9 + slot:02d}",
                    "tranche": slot,
                },
            )
            assert opened.status_code == 201, opened.text
            position_ids.append(opened.json()["id"])

        refreshed = client.post("/api/market/refresh")

        assert refreshed.status_code == 200
        payload = refreshed.json()
        assert not any(decision["eligible"] for decision in payload["leaps"])
        assert payload["leaps_fifo"] == {
            "required": True,
            "candidate": {
                "position_id": position_ids[0],
                "slot": 1,
                "opened_on": "2026-07-10",
            },
        }
