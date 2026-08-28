from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base
from app.main import app


@contextmanager
def settlement_client():
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
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_partial_leaps_profit_goes_to_cash_and_later_loss_reduces_leaps() -> None:
    with settlement_client() as client:
        client.post(
            "/api/portfolio/initialize",
            json={
                "age": 36,
                "opening_equity": 100000,
                "opening_date": "2026-07-01",
            },
        )
        position = client.post(
            "/api/positions",
            json={
                "bucket": "leaps",
                "symbol": "QQQ",
                "asset_type": "option",
                "direction": "long",
                "option_type": "call",
                "quantity": 2,
                "entry_price": 100,
                "opened_on": "2026-07-01",
                "expiration": "2027-07-01",
                "strike": 400,
                "tranche": 1,
            },
        ).json()

        partial = client.post(
            f"/api/positions/{position['id']}/close",
            json={"date": "2026-08-01", "price": 130, "quantity": 1},
        )

        assert partial.status_code == 200, partial.text
        assert partial.json()["status"] == "open"
        assert partial.json()["quantity"] == 1
        assert partial.json()["realized_profit"] == 3000.0
        after_profit = client.get("/api/portfolio/summary").json()["balances"]
        assert after_profit["cash"] == 8000.0
        assert after_profit["leaps"] == 25000.0
        capital_after_profit = client.get("/api/portfolio/summary").json()["capital"]
        assert capital_after_profit["leaps"] == {
            "assigned": 25000.0,
            "committed": 10000.0,
            "available": 15000.0,
            "cash_occupancy": 0.0,
        }

        closed = client.post(
            f"/api/positions/{position['id']}/close",
            json={"date": "2026-09-01", "price": 80, "quantity": 1},
        )

        assert closed.status_code == 200
        assert closed.json()["status"] == "closed"
        assert closed.json()["realized_profit"] == 1000.0
        after_loss = client.get("/api/portfolio/summary").json()["balances"]
        assert after_loss["cash"] == 8000.0
        assert after_loss["leaps"] == 23000.0
        capital_after_close = client.get("/api/portfolio/summary").json()["capital"]
        assert capital_after_close["leaps"] == {
            "assigned": 23000.0,
            "committed": 0.0,
            "available": 23000.0,
            "cash_occupancy": 0.0,
        }

        ledger = client.get("/api/profit-ledger").json()
        automatic = [entry for entry in ledger["entries"] if entry["source"] == "leaps"]
        assert [entry["amount"] for entry in automatic] == [-2000.0, 3000.0]
        assert all(entry["automatic"] and not entry["deletable"] for entry in automatic)
        assert ledger["summary"]["leaps_realized"] == 1000.0
        assert ledger["summary"]["available"] == 1000.0


def test_leaps_loss_uses_leaps_bucket_then_reduces_cash() -> None:
    with settlement_client() as client:
        client.post(
            "/api/portfolio/initialize",
            json={
                "age": 36,
                "opening_equity": 100000,
                "opening_date": "2026-07-01",
            },
        )
        position = client.post(
            "/api/positions",
            json={
                "bucket": "leaps",
                "symbol": "QQQ",
                "asset_type": "option",
                "direction": "long",
                "option_type": "call",
                "quantity": 1,
                "entry_price": 100,
                "opened_on": "2026-07-01",
                "expiration": "2027-07-01",
                "strike": 400,
                "tranche": 1,
            },
        ).json()

        closed = client.post(
            f"/api/positions/{position['id']}/close",
            json={"date": "2026-08-01", "price": 10},
        )

        assert closed.status_code == 200
        balances = client.get("/api/portfolio/summary").json()["balances"]
        assert balances["leaps"] == 16000.0
        assert balances["cash"] == 5000.0


def test_qld_partial_sale_releases_stock_cost_and_posts_only_profit_to_cash() -> None:
    with settlement_client() as client:
        client.post(
            "/api/portfolio/initialize",
            json={
                "age": 36,
                "opening_equity": 100000,
                "opening_date": "2026-07-01",
            },
        )
        position = client.post(
            "/api/positions",
            json={
                "bucket": "leaps",
                "symbol": "QLD",
                "asset_type": "equity",
                "direction": "long",
                "quantity": 100,
                "entry_price": 80,
                "opened_on": "2026-07-29",
                "tranche": 1,
            },
        ).json()

        sold = client.post(
            f"/api/positions/{position['id']}/close",
            json={"date": "2026-08-10", "price": 85, "quantity": 50},
        )

        assert sold.status_code == 200, sold.text
        assert sold.json()["quantity"] == 50
        assert sold.json()["realized_profit"] == 250.0
        summary = client.get("/api/portfolio/summary").json()
        assert summary["balances"]["cash"] == 5250.0
        assert summary["balances"]["leaps"] == 25000.0
        assert summary["capital"]["leaps"]["committed"] == 4000.0
        assert summary["capital"]["leaps"]["available"] == 21000.0
        ledger = client.get("/api/profit-ledger").json()
        entry = next(item for item in ledger["entries"] if item["source"] == "leaps")
        assert entry["note"] == "QLD 槽位 1 卖出"
