from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base
from app.main import app


def profit_client() -> TestClient:
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


def initialize_profit_account(client: TestClient) -> None:
    response = client.post(
        "/api/portfolio/initialize",
        json={
            "age": 36,
            "opening_equity": 100000,
            "opening_date": "2026-07-01",
        },
    )
    assert response.status_code == 201


def test_empty_profit_ledger_has_zero_distributable_balance() -> None:
    client = profit_client()

    response = client.get("/api/profit-ledger")

    assert response.status_code == 200
    assert response.json() == {
        "summary": {
            "wheel_realized": 0.0,
            "leaps_realized": 0.0,
            "other_realized": 0.0,
            "net_realized": 0.0,
            "allocated": 0.0,
            "available": 0.0,
        },
        "entries": [],
    }
    app.dependency_overrides.clear()


def test_signed_manual_results_change_leaps_and_available_totals() -> None:
    client = profit_client()
    profit = client.post(
        "/api/profit-ledger/realized",
        json={
            "source": "leaps",
            "occurred_on": "2026-07-18",
            "amount": 5000,
            "note": "第一批 LEAPS 部分止盈",
        },
    )
    loss = client.post(
        "/api/profit-ledger/realized",
        json={
            "source": "leaps",
            "occurred_on": "2026-07-19",
            "amount": -500,
            "note": "第二批止损",
        },
    )

    assert profit.status_code == 201
    assert loss.status_code == 201
    payload = loss.json()
    assert payload["summary"]["leaps_realized"] == 4500.0
    assert payload["summary"]["net_realized"] == 4500.0
    assert payload["summary"]["available"] == 4500.0
    assert [row["amount"] for row in payload["entries"]] == [-500.0, 5000.0]
    assert all(row["automatic"] is False for row in payload["entries"])
    assert all("fee" not in row for row in payload["entries"])
    app.dependency_overrides.clear()


def test_allocation_requires_available_profit_and_records_details() -> None:
    client = profit_client()
    initialize_profit_account(client)
    client.post(
        "/api/profit-ledger/realized",
        json={"source": "leaps", "occurred_on": "2026-07-18", "amount": 2000},
    )

    rejected = client.post(
        "/api/profit-ledger/allocations",
        json={
            "occurred_on": "2026-07-20",
            "amount": 2500,
            "allocations": {"core": 1500, "cash": 1000},
        },
    )
    accepted = client.post(
        "/api/profit-ledger/allocations",
        json={
            "occurred_on": "2026-07-20",
            "amount": 1200,
            "allocations": {"core": 700, "cash": 500},
            "note": "按目标缺口确认",
        },
    )

    assert rejected.status_code == 409
    assert "超过当前可分配收益" in rejected.text
    assert accepted.status_code == 201
    payload = accepted.json()
    assert payload["summary"]["allocated"] == 1200.0
    assert payload["summary"]["available"] == 800.0
    allocation = payload["entries"][0]
    assert allocation["entry_type"] == "allocation"
    assert allocation["amount"] == -1200.0
    assert allocation["allocations"] == {"core": 700.0, "cash": 500.0}
    balances = client.get("/api/portfolio/summary").json()["balances"]
    assert balances["cash"] == 6300.0
    assert balances["core"] == 70700.0
    app.dependency_overrides.clear()


def test_settled_wheel_profit_is_derived_and_voiding_source_removes_it() -> None:
    client = profit_client()
    opened = client.post(
        "/api/wheel/portfolio/puts",
        json={
            "batch_number": 1,
            "trade_date": "2026-07-18",
            "expiration": "2026-08-21",
            "strike": 50,
            "premium": 1.5,
            "quantity": 12,
            "entry_tqqq_price": 55,
        },
    ).json()
    put_id = opened["rounds"][0]["puts"][0]["id"]
    client.post(
        f"/api/wheel/portfolio/puts/{put_id}/close",
        json={"date": "2026-07-25", "premium": 0.5},
    )

    settled = client.get("/api/profit-ledger").json()
    assert settled["summary"]["wheel_realized"] == 1200.0
    assert settled["summary"]["available"] == 1200.0
    assert settled["entries"][0] == {
        "id": f"wheel-put:{put_id}",
        "entry_type": "realized",
        "source": "wheel",
        "occurred_on": "2026-07-25",
        "amount": 1200.0,
        "note": f"Sell Put #{put_id} 平仓",
        "automatic": True,
        "deletable": False,
        "allocations": {},
    }

    voided = client.post(
        f"/api/wheel/portfolio/puts/{put_id}/void",
        json={"confirmation": "VOID", "reason": "录入错误"},
    )
    assert voided.status_code == 200
    cleared = client.get("/api/profit-ledger").json()
    assert cleared["summary"]["wheel_realized"] == 0.0
    assert cleared["entries"] == []
    app.dependency_overrides.clear()


def test_partial_put_assignment_and_remaining_close_are_separate_ledger_rows() -> None:
    client = profit_client()
    opened = client.post(
        "/api/wheel/portfolio/puts",
        json={
            "batch_number": 1,
            "trade_date": "2026-07-18",
            "expiration": "2026-08-21",
            "strike": 50,
            "premium": 1.5,
            "quantity": 2,
            "entry_tqqq_price": 55,
        },
    ).json()
    put_id = opened["rounds"][0]["puts"][0]["id"]
    assigned = client.post(
        f"/api/wheel/portfolio/puts/{put_id}/assign",
        json={"date": "2026-07-20", "contracts": 1},
    ).json()
    share_id = assigned["rounds"][0]["puts"][0]["share_lots"][0]["id"]
    client.post(
        f"/api/wheel/portfolio/puts/{put_id}/close",
        json={"date": "2026-07-25", "premium": 0.5},
    )

    payload = client.get("/api/profit-ledger").json()

    assert payload["summary"]["wheel_realized"] == 250.0
    assert [row["id"] for row in payload["entries"]] == [
        f"wheel-put:{put_id}",
        f"wheel-put-assignment:{share_id}",
    ]
    assert [row["occurred_on"] for row in payload["entries"]] == [
        "2026-07-25",
        "2026-07-20",
    ]
    assert [row["amount"] for row in payload["entries"]] == [100.0, 150.0]
    app.dependency_overrides.clear()


def test_manual_profit_entry_requires_typed_confirmation_before_deletion() -> None:
    client = profit_client()
    created = client.post(
        "/api/profit-ledger/realized",
        json={"source": "other", "occurred_on": "2026-07-18", "amount": 300},
    ).json()
    entry_id = created["entries"][0]["id"]

    rejected = client.post(
        f"/api/profit-ledger/entries/{entry_id}/delete",
        json={"confirmation": "delete"},
    )
    deleted = client.post(
        f"/api/profit-ledger/entries/{entry_id}/delete",
        json={"confirmation": "DELETE"},
    )

    assert rejected.status_code == 422
    assert deleted.status_code == 200
    assert deleted.json()["summary"]["available"] == 0.0
    assert deleted.json()["entries"] == []
    app.dependency_overrides.clear()
