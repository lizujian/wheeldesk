from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base
from app.main import app


def client_with_database() -> TestClient:
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
    return client


def test_manual_core_and_qqq_leaps_positions_can_be_recorded() -> None:
    client = client_with_database()
    core = client.post(
        "/api/positions",
        json={
            "bucket": "core",
            "symbol": "BRK.B",
            "asset_type": "equity",
            "quantity": 10,
            "entry_price": 500,
            "opened_on": "2026-07-10",
            "core_signal_code": "pullback",
            "fees": 1,
        },
    )
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
            "opened_on": "2026-07-10",
            "expiration": "2027-07-09",
            "strike": 400,
            "delta": 0.8,
            "tranche": 1,
            "fees": 1,
        },
    )

    assert core.status_code == 201
    assert core.json()["current_value"] == 5000.0
    core_event = next(
        event
        for event in client.get("/api/ledger/events").json()
        if event["event_type"] == "position_open" and event["bucket"] == "core"
    )
    assert core_event["details"]["core_signal_code"] == "pullback"
    assert leaps.status_code == 201
    assert leaps.json()["current_value"] == 10000.0
    assert leaps.json()["total_loss_impact"] == 10000.0
    assert len(client.get("/api/positions").json()) == 2
    app.dependency_overrides.clear()


def test_tqqq_leaps_is_rejected_and_position_can_be_marked_and_closed() -> None:
    client = client_with_database()
    rejected = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "TQQQ",
            "asset_type": "option",
            "direction": "long",
            "option_type": "call",
            "quantity": 1,
            "entry_price": 20,
            "opened_on": "2026-07-10",
            "expiration": "2027-07-09",
            "strike": 50,
            "delta": 0.8,
            "tranche": 1,
        },
    )
    assert rejected.status_code == 422
    assert "禁止使用 TQQQ" in rejected.text

    opened = client.post(
        "/api/positions",
        json={
            "bucket": "core",
            "symbol": "BRK.B",
            "asset_type": "equity",
            "quantity": 2,
            "entry_price": 500,
            "opened_on": "2026-07-10",
        },
    ).json()
    marked = client.patch(f"/api/positions/{opened['id']}/mark", json={"price": 550})
    closed = client.post(
        f"/api/positions/{opened['id']}/close",
        json={"date": "2026-08-10", "price": 550, "fees": 2},
    )

    assert marked.json()["unrealized_profit"] == 100.0
    assert closed.status_code == 409
    assert "仅允许通过账户再平衡卖出" in closed.text
    assert client.get("/api/positions").json()[0]["status"] == "open"
    app.dependency_overrides.clear()


def test_qqq_leaps_no_longer_requires_delta_input() -> None:
    client = client_with_database()

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
    assert opened.json()["delta"] is None
    app.dependency_overrides.clear()


def test_leaps_dte_outside_guidance_is_allowed_for_qqq_and_club_calls() -> None:
    client = client_with_database()

    short_qqq = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "QQQ",
            "asset_type": "option",
            "direction": "long",
            "option_type": "call",
            "quantity": 1,
            "entry_price": 50,
            "opened_on": "2026-08-24",
            "expiration": "2027-02-19",
            "strike": 600,
            "tranche": 1,
        },
    )
    long_club = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "AAPL",
            "asset_type": "option",
            "direction": "long",
            "option_type": "call",
            "quantity": 1,
            "entry_price": 80,
            "opened_on": "2026-08-24",
            "expiration": "2028-08-18",
            "strike": 250,
            "tranche": 1,
            "underlying_entry_price": 310,
        },
    )

    assert short_qqq.status_code == 201, short_qqq.text
    assert long_club.status_code == 201, long_club.text
    app.dependency_overrides.clear()


def test_qld_equity_can_substitute_for_a_leaps_tranche() -> None:
    client = client_with_database()

    opened = client.post(
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
    )
    missing_tranche = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "QLD",
            "asset_type": "equity",
            "direction": "long",
            "quantity": 100,
            "entry_price": 80,
            "opened_on": "2026-07-29",
        },
    )
    wrong_symbol = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "SSO",
            "asset_type": "equity",
            "direction": "long",
            "quantity": 100,
            "entry_price": 90,
            "opened_on": "2026-07-29",
            "tranche": 2,
        },
    )
    option_fields = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "QLD",
            "asset_type": "equity",
            "direction": "long",
            "quantity": 100,
            "entry_price": 80,
            "opened_on": "2026-07-29",
            "tranche": 2,
            "delta": 0.7,
        },
    )
    slot_five = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "QLD",
            "asset_type": "equity",
            "direction": "long",
            "quantity": 10,
            "entry_price": 80,
            "opened_on": "2026-07-30",
            "tranche": 5,
        },
    )
    slot_six = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "QLD",
            "asset_type": "equity",
            "direction": "long",
            "quantity": 10,
            "entry_price": 80,
            "opened_on": "2026-07-30",
            "tranche": 6,
        },
    )

    assert opened.status_code == 201, opened.text
    assert opened.json()["symbol"] == "QLD"
    assert opened.json()["multiplier"] == 1
    assert opened.json()["current_value"] == 8000.0
    assert opened.json()["expiration"] is None
    assert opened.json()["exit_decision"]["code"] == "hold"
    assert opened.json()["exit_decision"]["target_return"] == 0.25
    assert opened.json()["exit_decision"]["dte"] is None
    marked = client.patch(
        f"/api/positions/{opened.json()['id']}/mark", json={"price": 160}
    )
    assert marked.json()["exit_decision"]["code"] == "take_profit"
    assert marked.json()["exit_decision"]["actionable"] is True
    assert missing_tranche.status_code == 422
    assert "批次" in missing_tranche.text
    assert wrong_symbol.status_code == 422
    assert "只允许 QLD" in wrong_symbol.text
    assert option_fields.status_code == 422
    assert "不需要期权合约参数" in option_fields.text
    assert slot_five.status_code == 201, slot_five.text
    assert slot_six.status_code == 422
    app.dependency_overrides.clear()


def test_trillion_club_call_does_not_require_underlying_price_and_limits_two_slots() -> None:
    client = client_with_database()
    accepted = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "GOOG",
            "asset_type": "option",
            "direction": "long",
            "option_type": "call",
            "quantity": 1,
            "entry_price": 40,
            "opened_on": "2026-08-24",
            "expiration": "2027-08-20",
            "strike": 250,
            "tranche": 2,
        },
    )
    third_slot = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "GOOG",
            "asset_type": "option",
            "direction": "long",
            "option_type": "call",
            "quantity": 1,
            "entry_price": 40,
            "opened_on": "2026-08-24",
            "expiration": "2027-08-20",
            "strike": 250,
            "tranche": 3,
            "underlying_entry_price": 310,
        },
    )
    excluded = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "MU",
            "asset_type": "option",
            "direction": "long",
            "option_type": "call",
            "quantity": 1,
            "entry_price": 20,
            "opened_on": "2026-08-24",
            "expiration": "2027-08-20",
            "strike": 150,
            "tranche": 1,
            "underlying_entry_price": 180,
        },
    )
    wrong_google_class = client.post(
        "/api/positions",
        json={
            "bucket": "leaps",
            "symbol": "GOOGL",
            "asset_type": "option",
            "direction": "long",
            "option_type": "call",
            "quantity": 1,
            "entry_price": 40,
            "opened_on": "2026-08-24",
            "expiration": "2027-08-20",
            "strike": 250,
            "tranche": 1,
            "underlying_entry_price": 310,
        },
    )

    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["leaps_category"] == "club"
    assert accepted.json()["underlying_entry_price"] is None
    assert third_slot.status_code == 422
    assert "最多两个槽位" in third_slot.text
    assert excluded.status_code == 422
    assert wrong_google_class.status_code == 422
    app.dependency_overrides.clear()


def test_core_purchase_automatically_funds_only_the_core_shortfall_from_cash() -> None:
    client = client_with_database()
    first = client.post(
        "/api/positions",
        json={
            "bucket": "core",
            "symbol": "BRK.B",
            "asset_type": "equity",
            "quantity": 98,
            "entry_price": 500,
            "opened_on": "2026-07-10",
        },
    )
    second = client.post(
        "/api/positions",
        json={
            "bucket": "core",
            "symbol": "BRK.B",
            "asset_type": "equity",
            "quantity": 4,
            "entry_price": 500,
            "opened_on": "2026-07-20",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    summary = client.get("/api/portfolio/summary").json()
    assert summary["balances"]["core"] == 51000.0
    assert summary["balances"]["cash"] == 4000.0
    funding_events = [
        event
        for event in client.get("/api/ledger/events").json()
        if event["event_type"] == "core_auto_funding"
    ]
    assert [event["amount"] for event in funding_events] == [1000.0, -1000.0]
    app.dependency_overrides.clear()


def test_core_purchase_is_atomic_when_available_cash_cannot_cover_shortfall() -> None:
    client = client_with_database()
    client.post(
        "/api/positions",
        json={
            "bucket": "core",
            "symbol": "BRK.B",
            "asset_type": "equity",
            "quantity": 100,
            "entry_price": 500,
            "opened_on": "2026-07-10",
        },
    )

    rejected = client.post(
        "/api/positions",
        json={
            "bucket": "core",
            "symbol": "BRK.B",
            "asset_type": "equity",
            "quantity": 30,
            "entry_price": 500,
            "opened_on": "2026-07-20",
        },
    )

    assert rejected.status_code == 409
    assert "可用现金不足" in rejected.text
    assert len(client.get("/api/positions").json()) == 1
    summary = client.get("/api/portfolio/summary").json()
    assert summary["balances"]["core"] == 50000.0
    assert summary["balances"]["cash"] == 5000.0
    app.dependency_overrides.clear()
