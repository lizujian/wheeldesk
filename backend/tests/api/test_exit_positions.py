from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base
from app.main import app


def exit_client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)

    def override_session():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_lightweight_exit_position_workflow_and_summary() -> None:
    client = exit_client()
    stock = client.post(
        "/api/exit-positions",
        json={
            "name": "AAPL 正股",
            "position_type": "stock",
            "current_value": 30000,
            "target_value": 40000,
            "cost_price": 185.5,
            "note": "历史仓位",
        },
    )
    sell_put = client.post(
        "/api/exit-positions",
        json={
            "name": "TQQQ Sell Put",
            "position_type": "sell_put",
            "current_value": -3000,
            "target_value": -500,
        },
    )

    assert stock.status_code == 201
    assert stock.json()["cost_price"] == 185.5
    assert sell_put.status_code == 201
    listing = client.get("/api/exit-positions").json()
    assert listing["summary"] == {
        "active_count": 2,
        "target_reached_count": 0,
        "asset_value": 30000.0,
        "option_float_pnl": -3000.0,
        "recovered_cash": 0.0,
    }

    updated = client.patch(
        f"/api/exit-positions/{sell_put.json()['id']}",
        json={"current_value": -400, "target_value": -500, "note": "接近退出"},
    )
    assert updated.status_code == 200
    assert updated.json()["target_reached"] is True

    stock_updated = client.patch(
        f"/api/exit-positions/{stock.json()['id']}",
        json={"cost_price": 190.25},
    )
    assert stock_updated.status_code == 200
    assert stock_updated.json()["cost_price"] == 190.25

    partial = client.post(
        f"/api/exit-positions/{stock.json()['id']}/partial-exit",
        json={"recovered_cash": 10000, "remaining_value": 21000, "note": "已卖一部分"},
    )
    assert partial.json()["status"] == "partial"
    assert partial.json()["core_transfer_suggestion"] == 10000.0

    completed = client.post(
        f"/api/exit-positions/{stock.json()['id']}/complete-exit",
        json={"recovered_cash": 21500},
    )
    assert completed.json()["status"] == "exited"
    assert completed.json()["recovered_cash"] == 31500.0
    app.dependency_overrides.clear()


def test_rejects_negative_stock_value_but_allows_negative_option_pnl() -> None:
    client = exit_client()

    stock = client.post(
        "/api/exit-positions",
        json={
            "name": "AAPL",
            "position_type": "stock",
            "current_value": -1,
            "target_value": 100,
        },
    )
    covered_call = client.post(
        "/api/exit-positions",
        json={
            "name": "AAPL Covered Call",
            "position_type": "covered_call",
            "current_value": -800,
            "target_value": 200,
        },
    )

    assert stock.status_code == 409
    assert covered_call.status_code == 201
    app.dependency_overrides.clear()
