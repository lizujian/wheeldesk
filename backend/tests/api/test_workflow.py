from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base
from app.main import app
from app.market.sample import SampleMarketDataProvider
from app.api.market import get_market_provider


def test_manual_workflow_from_onboarding_to_profit_redistribution() -> None:
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
    app.dependency_overrides[get_market_provider] = lambda: SampleMarketDataProvider(
        as_of=date(2026, 7, 9)
    )
    client = TestClient(app)

    initialized = client.post(
        "/api/portfolio/initialize",
        json={
            "age": 30,
            "opening_equity": 100000,
            "opening_date": "2026-07-01",
        },
    )
    assert initialized.status_code == 201
    assert initialized.json()["targets"]["wheel"]["amount"] == 20000.0
    assert initialized.json()["other_holdings_value"] == 0.0
    assert initialized.json()["balances"] == {
        "core": 50000.0,
        "cash": 5000.0,
        "wheel": 20000.0,
        "leaps": 25000.0,
        "unallocated": 0.0,
    }

    deposited = client.post(
        "/api/portfolio/deposits",
        json={"amount": 1000, "date": "2026-07-02", "note": "新增资金"},
    )
    assert deposited.status_code == 200
    assert deposited.json()["balances"]["cash"] == 6000.0
    assert deposited.json()["balances"]["unallocated"] == 0.0

    updated_other = client.post(
        "/api/portfolio/other-holdings",
        json={"amount": 25000},
    )
    assert updated_other.status_code == 200
    assert updated_other.json()["other_holdings_value"] == 25000.0
    assert updated_other.json()["total_equity"] == 101000.0
    assert updated_other.json()["targets"]["wheel"]["amount"] == 20200.0

    cleared_other = client.post(
        "/api/portfolio/other-holdings",
        json={"amount": 0},
    )
    assert cleared_other.status_code == 200
    assert cleared_other.json()["other_holdings_value"] == 0.0

    refreshed = client.post("/api/market/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["source"] == "sample"
    assert refreshed.json()["wheel"]["dte_range"] == [30, 45]
    assert refreshed.json()["wheel"]["reference_strike"] > 0
    assert client.get("/api/signals").status_code == 200

    put = client.post(
        "/api/wheel/puts",
        json={
            "trade_date": "2026-07-10",
            "expiration": "2026-08-14",
            "strike": 100,
            "premium": 2,
            "quantity": 1,
            "fees": 1,
        },
    )
    assert put.status_code == 201
    cycle_id = put.json()["id"]
    assert put.json()["state"] == "put_open"

    assigned = client.post(
        f"/api/wheel/{cycle_id}/assign-put",
        json={"date": "2026-08-14"},
    )
    assert assigned.json()["adjusted_share_basis"] == 98.0

    call = client.post(
        f"/api/wheel/{cycle_id}/calls",
        json={
            "trade_date": "2026-08-17",
            "expiration": "2026-09-18",
            "strike": 105,
            "premium": 1,
            "quantity": 1,
            "fees": 1,
        },
    )
    assert call.status_code == 201
    assert call.json()["state"] == "call_open"

    closed = client.post(
        f"/api/wheel/{cycle_id}/call-away",
        json={"date": "2026-09-18", "fee": 2},
    )
    assert closed.json()["state"] == "closed"
    assert closed.json()["realized_profit"] == 800.0

    recommendation = client.post(
        "/api/portfolio/redistribution",
        json={"distributable_profit": 800},
    )
    assert recommendation.status_code == 200
    assert recommendation.json()["unallocated"] == 0.0
    assert sum(recommendation.json()["allocations"].values()) == 800.0

    app.dependency_overrides.clear()
