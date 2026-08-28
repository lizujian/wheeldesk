from contextlib import contextmanager
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base, BucketBalance, PortfolioProfile
from app.main import app


@contextmanager
def wheel_client(total: int = 312_500, funded: int = 100_000):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(engine, expire_on_commit=False, class_=Session)
    with testing_session() as session:
        session.add(
            PortfolioProfile(
                id=1,
                age=30,
                opening_equity=total,
                opening_date=date(2026, 7, 1),
                currency="USD",
            )
        )
        session.add_all(
            [
                BucketBalance(bucket="wheel", amount=funded),
                BucketBalance(bucket="unallocated", amount=total - funded),
            ]
        )
        session.commit()

    def override_session():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def put_payload(**overrides):
    payload = {
        "batch_number": 1,
        "trade_date": "2026-07-18",
        "expiration": "2026-08-21",
        "strike": 50,
        "premium": 1.5,
        "quantity": 12,
        "entry_tqqq_price": 55,
    }
    return payload | overrides


def test_overview_and_over_budget_put_are_serialized_as_one_snapshot() -> None:
    with wheel_client() as client:
        empty = client.get("/api/wheel/overview")
        assert empty.status_code == 200
        assert empty.json()["budget"] == {
            "budget": 140625.0,
            "target_fraction": 0.45,
            "funded": 100000.0,
            "funding_gap": 40625.0,
            "funding_excess": 0.0,
            "unfunded_exposure": 0.0,
            "exposure": 0.0,
            "available": 140625.0,
            "over_budget": 0.0,
            "usage_fraction": 0.0,
        }
        assert empty.json()["recommendations"] == {"first": 84375.0, "second": 56250.0}
        assert empty.json()["rounds"] == []

        created = client.post(
            "/api/wheel/portfolio/puts",
            json=put_payload(quantity=22),
        )

        assert created.status_code == 201
        overview = created.json()
        assert overview["budget"]["exposure"] == 110000.0
        assert overview["budget"]["over_budget"] == 0.0
        assert overview["budget"]["available"] == 30625.0
        assert overview["recommendations"] == {"first": 30625.0, "second": 30625.0}
        put = overview["rounds"][0]["puts"][0]
        assert put["collateral"] == 110000.0
        assert put["opening_dte"] == 34
        assert put["opening_annualized_return"] == 0.322059
        assert put["early_close_annualized_return"] is None
        assert put["early_close_return_kind"] is None
        assert put["open_quantity"] == 22
        assert put["share_lots"] == []
        assert "fees" not in put


def test_club_put_requires_earnings_confirmation_and_one_active_cycle_per_symbol() -> None:
    with wheel_client() as client:
        rejected = client.post(
            "/api/wheel/portfolio/puts",
            json=put_payload(
                symbol="AAPL",
                batch_number=1,
                earnings_confirmed=False,
            ),
        )
        assert rejected.status_code == 422

        created = client.post(
            "/api/wheel/portfolio/puts",
            json=put_payload(
                symbol="AAPL",
                batch_number=1,
                earnings_confirmed=True,
            ),
        )
        assert created.status_code == 201, created.text
        put = created.json()["rounds"][0]["puts"][0]
        assert put["symbol"] == "AAPL"
        assert put["earnings_confirmed"] is True
        assert put["entry_underlying_price"] == 55.0

        duplicate = client.post(
            "/api/wheel/portfolio/puts",
            json=put_payload(
                symbol="AAPL",
                batch_number=1,
                earnings_confirmed=True,
                trade_date="2026-07-25",
            ),
        )
        assert duplicate.status_code == 409
        assert "已有活动车轮周期" in duplicate.json()["detail"]

        core_rejected = client.post(
            "/api/wheel/portfolio/puts",
            json=put_payload(
                symbol="BRK-B",
                batch_number=1,
                earnings_confirmed=True,
            ),
        )
        assert core_rejected.status_code == 422


def test_target_budget_is_calculated_even_when_wheel_bucket_is_empty() -> None:
    with wheel_client(total=179_726, funded=0) as client:
        overview = client.get("/api/wheel/overview")

        assert overview.status_code == 200
        assert overview.json()["budget"] == {
            "budget": 80876.7,
            "target_fraction": 0.45,
            "funded": 0.0,
            "funding_gap": 80876.7,
            "funding_excess": 0.0,
            "unfunded_exposure": 0.0,
            "exposure": 0.0,
            "available": 80876.7,
            "over_budget": 0.0,
            "usage_fraction": 0.0,
        }
        assert overview.json()["recommendations"] == {
            "first": 48526.02,
            "second": 32350.68,
        }


def test_put_edit_assign_calls_and_second_batch_remain_independent() -> None:
    with wheel_client() as client:
        first_overview = client.post(
            "/api/wheel/portfolio/puts", json=put_payload()
        ).json()
        first = first_overview["rounds"][0]["puts"][0]
        round_id = first["round_id"]

        edited = client.patch(
            f"/api/wheel/portfolio/puts/{first['id']}",
            json={"strike": 48, "quantity": 10},
        )
        assert edited.status_code == 200
        assert edited.json()["rounds"][0]["puts"][0]["collateral"] == 48000.0

        assigned = client.post(
            f"/api/wheel/portfolio/puts/{first['id']}/assign",
            json={"date": "2026-08-21", "contracts": 10},
        )
        assert assigned.status_code == 200
        shares = assigned.json()["rounds"][0]["puts"][0]["share_lots"][0]
        assert shares["remaining_quantity"] == 1000

        first_call = client.post(
            f"/api/wheel/portfolio/shares/{shares['id']}/calls",
            json={
                "trade_date": "2026-08-22",
                "expiration": "2026-09-18",
                "strike": 52,
                "premium": 1.2,
                "quantity": 4,
            },
        )
        assert first_call.status_code == 201
        second_call = client.post(
            f"/api/wheel/portfolio/shares/{shares['id']}/calls",
            json={
                "trade_date": "2026-08-22",
                "expiration": "2026-10-16",
                "strike": 55,
                "premium": 0.9,
                "quantity": 6,
            },
        )
        assert second_call.status_code == 201

        second = client.post(
            "/api/wheel/portfolio/puts",
            json=put_payload(
                round_id=round_id,
                batch_number=2,
                trade_date="2026-08-23",
                expiration="2026-09-25",
                strike=45,
                premium=1.1,
                quantity=8,
                entry_tqqq_price=50,
            ),
        )
        assert second.status_code == 201
        second_put = next(
            item for item in second.json()["rounds"][0]["puts"] if item["batch_number"] == 2
        )

        expired = client.post(
            f"/api/wheel/portfolio/puts/{second_put['id']}/expire",
            json={"date": "2026-09-25"},
        )
        lots = expired.json()["rounds"][0]["puts"]
        assert next(item for item in lots if item["batch_number"] == 2)["state"] == "expired"
        calls = next(item for item in lots if item["batch_number"] == 1)["share_lots"][0]["calls"]
        assert [item["state"] for item in calls] == ["open", "open"]


def test_option_close_call_away_and_void_confirmation() -> None:
    with wheel_client() as client:
        first = client.post("/api/wheel/portfolio/puts", json=put_payload()).json()
        put_id = first["rounds"][0]["puts"][0]["id"]

        missing_confirmation = client.post(
            f"/api/wheel/portfolio/puts/{put_id}/void",
            json={"confirmation": "NO", "reason": "录入错误"},
        )
        assert missing_confirmation.status_code == 422

        closed = client.post(
            f"/api/wheel/portfolio/puts/{put_id}/close",
            json={"date": "2026-07-25", "premium": 0.5},
        )
        put = closed.json()["rounds"][0]["puts"][0]
        assert put["state"] == "closed"
        assert put["realized_profit"] == 1200.0
        assert put["early_close_days"] == 7
        assert put["early_close_annualized_return"] == 1.042857
        assert put["early_close_return_kind"] == "actual"

        erroneous = client.post(
            "/api/wheel/portfolio/puts",
            json=put_payload(trade_date="2026-09-01", expiration="2026-10-09", quantity=2),
        ).json()
        bad_id = erroneous["rounds"][-1]["puts"][0]["id"]
        voided = client.post(
            f"/api/wheel/portfolio/puts/{bad_id}/void",
            json={"confirmation": "VOID", "reason": "数量录入错误"},
        )
        assert voided.status_code == 200
        voided_put = next(
            item
            for round_item in voided.json()["rounds"]
            for item in round_item["puts"]
            if item["id"] == bad_id
        )
        assert voided_put["state"] == "voided"
        assert voided_put["void_reason"] == "数量录入错误"

        assigned_source = client.post(
            "/api/wheel/portfolio/puts",
            json=put_payload(trade_date="2026-09-02", expiration="2026-10-16", quantity=2),
        ).json()
        source_id = assigned_source["rounds"][-1]["puts"][0]["id"]
        assigned = client.post(
            f"/api/wheel/portfolio/puts/{source_id}/assign",
            json={"date": "2026-10-16", "contracts": 2},
        ).json()
        share = next(
            item
            for round_item in assigned["rounds"]
            for put_item in round_item["puts"]
            for item in put_item["share_lots"]
            if put_item["id"] == source_id
        )
        call_result = client.post(
            f"/api/wheel/portfolio/shares/{share['id']}/calls",
            json={
                "trade_date": "2026-10-17",
                "expiration": "2026-11-20",
                "strike": 52,
                "premium": 1,
                "quantity": 2,
            },
        ).json()
        call = next(
            item
            for round_item in call_result["rounds"]
            for put_item in round_item["puts"]
            for share_item in put_item["share_lots"]
            for item in share_item["calls"]
            if put_item["id"] == source_id
        )
        called = client.post(
            f"/api/wheel/portfolio/calls/{call['id']}/call-away",
            json={"date": "2026-11-20"},
        )
        assert called.status_code == 200

        chain = client.post(
            f"/api/wheel/portfolio/puts/{source_id}/void-chain",
            json={"confirmation": "VOID", "reason": "整链测试数据"},
        )
        assert chain.status_code == 200
        chain_put = next(
            item
            for round_item in chain.json()["rounds"]
            for item in round_item["puts"]
            if item["id"] == source_id
        )
        assert chain_put["state"] == "voided"
        assert chain_put["share_lots"][0]["state"] == "voided"
        assert chain_put["share_lots"][0]["calls"][0]["state"] == "voided"


def test_legacy_current_route_stays_available() -> None:
    with wheel_client() as client:
        response = client.get("/api/wheel/current")
        assert response.status_code == 200
        assert response.json() == {"state": "waiting_put"}
