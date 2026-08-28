from contextlib import contextmanager
from datetime import date, timedelta
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
from app.market.base import MarketDataError, MarketSeries


class EquityProvider:
    def __init__(self) -> None:
        self.fail_symbols: set[str] = {"BAD"}

    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries:
        if symbol in self.fail_symbols:
            raise MarketDataError(f"{symbol} unavailable")
        prices = {"QQQ": "500", "TQQQ": "80", "BRK.B": "510", "VOO": "600", "VIX": "18", "AAPL": "220", "QLD": "90"}
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
