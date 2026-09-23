from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base
from app.main import app


@contextmanager
def rebalancing_client():
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


def initialize(
    client: TestClient,
    opening_date: str = "2026-01-31",
    age: int = 30,
) -> None:
    response = client.post(
        "/api/portfolio/initialize",
        json={
            "age": age,
            "opening_equity": 100000,
            "opening_date": opening_date,
        },
    )
    assert response.status_code == 201, response.text


def open_core(client: TestClient, quantity: int, price: int) -> dict:
    response = client.post(
        "/api/positions",
        json={
            "bucket": "core",
            "symbol": "BRK.B",
            "asset_type": "equity",
            "quantity": quantity,
            "entry_price": price,
            "opened_on": "2026-02-02",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_review_schedule_supports_due_and_manual_read_only_evaluation() -> None:
    with rebalancing_client() as client:
        initialize(client)

        early = client.get("/api/rebalancing", params={"as_of": "2026-07-30"})
        due = client.post(
            "/api/rebalancing/evaluate", json={"date": "2026-07-31"}
        )

        assert early.status_code == 200, early.text
        assert early.json()["schedule"] == {
            "last_rebalanced_on": None,
            "next_review_on": "2026-07-31",
            "due": False,
        }
        assert due.status_code == 200, due.text
        assert due.json()["schedule"]["due"] is True
        unchanged = client.get(
            "/api/rebalancing", params={"as_of": "2026-07-31"}
        ).json()
        assert unchanged["schedule"]["last_rebalanced_on"] is None


def test_rebalancing_does_not_rebalance_between_option_sub_strategies() -> None:
    with rebalancing_client() as client:
        initialize(client, age=36)
        for target, amount in (("cash", 5000), ("wheel", 13200)):
            moved = client.post(
                "/api/portfolio/transfers",
                json={
                    "source": "leaps",
                    "target": target,
                    "amount": amount,
                    "date": "2026-02-01",
                    "note": "模拟旧策略比例",
                },
            )
            assert moved.status_code == 200, moved.text

        payload = client.get(
            "/api/rebalancing", params={"as_of": "2026-08-10"}
        ).json()

        assert "transition" not in payload
        assert payload["economic"]["buckets"]["options"]["value"] == 20000.0
        assert payload["economic"]["buckets"]["options"]["target_fraction"] == 0.25


def test_economic_allocation_uses_core_appreciation_and_leaps_drawdown() -> None:
    with rebalancing_client() as client:
        initialize(client)
        core = open_core(client, quantity=10, price=100)
        client.patch(f"/api/positions/{core['id']}/mark", json={"price": 200})
        leaps = client.post(
            "/api/positions",
            json={
                "bucket": "leaps",
                "symbol": "QQQ",
                "asset_type": "option",
                "direction": "long",
                "option_type": "call",
                "quantity": 1,
                "entry_price": 100,
                "opened_on": "2026-02-02",
                "expiration": "2027-02-01",
                "strike": 400,
                "tranche": 1,
            },
        ).json()
        client.patch(f"/api/positions/{leaps['id']}/mark", json={"price": 50})

        payload = client.get(
            "/api/rebalancing", params={"as_of": "2026-07-31"}
        ).json()

        assert payload["assigned"]["total"] == 100000.0
        assert payload["economic"]["total"] == 96000.0
        assert payload["economic"]["buckets"]["core"]["value"] == 71000.0
        assert payload["economic"]["buckets"]["options"]["value"] == 20000.0
        assert payload["economic"]["buckets"]["cash"]["value"] == 5000.0
        assert payload["economic"]["buckets"]["core"]["fraction"] == 71000 / 96000


def test_recommendations_prioritize_margin_then_cash_restoration() -> None:
    with rebalancing_client() as client:
        initialize(client)
        client.post(
            "/api/wheel/portfolio/puts",
            json={
                "batch_number": 1,
                "trade_date": "2026-07-01",
                "expiration": "2026-08-14",
                "strike": 50,
                "premium": 1.5,
                "quantity": 24,
                "entry_tqqq_price": 55,
            },
        )

        payload = client.get(
            "/api/rebalancing", params={"as_of": "2026-07-31"}
        ).json()

        assert payload["capital"]["cash"]["margin_shortfall"] == 90000.0
        assert payload["recommendations"][0]["code"] == "eliminate_margin"
        assert payload["recommendations"][0]["amount"] == 90000.0
        assert payload["recommendations"][1]["code"] == "restore_cash"


def test_due_core_overweight_allows_fifo_actual_sale_and_no_trade_confirmation() -> None:
    with rebalancing_client() as client:
        initialize(client)
        core = open_core(client, quantity=100, price=500)
        client.patch(f"/api/positions/{core['id']}/mark", json={"price": 1100})

        evaluated = client.get(
            "/api/rebalancing", params={"as_of": "2026-07-31"}
        ).json()

        assert evaluated["core_decision"]["code"] == "sell"
        assert evaluated["core_decision"]["actionable"] is True
        assert evaluated["core_decision"]["sell_amount"] == 10000.0
        assert evaluated["core_decision"]["estimated_shares"] == 9.0909

        sold = client.post(
            "/api/rebalancing/core-sale",
            json={"date": "2026-07-31", "quantity": 10, "price": 1100},
        )

        assert sold.status_code == 200, sold.text
        assert sold.json()["sale"]["cost_basis"] == 5000.0
        assert sold.json()["sale"]["proceeds"] == 11000.0
        assert sold.json()["snapshot"]["schedule"]["last_rebalanced_on"] == "2026-07-31"

    with rebalancing_client() as client:
        initialize(client)
        confirmed = client.post(
            "/api/rebalancing/confirm-no-trade",
            json={"date": "2026-07-31"},
        )

        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["schedule"]["last_rebalanced_on"] == "2026-07-31"
        assert confirmed.json()["schedule"]["next_review_on"] == "2027-01-31"
