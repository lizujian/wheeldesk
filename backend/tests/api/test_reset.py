from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import (
    Base,
    BrokerImportRecord,
    OtherHoldingRecord,
    ProfitLedgerEntry,
    RealizedCashPosting,
    WheelCallLot,
    WheelPutLot,
    WheelRound,
    WheelShareLot,
)
from app.main import app
from app.services.wheel_portfolio import WheelPortfolioService


def reset_client():
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
    return TestClient(app), sessions


def seed_data(client: TestClient) -> None:
    client.post(
        "/api/portfolio/initialize",
        json={
            "age": 30,
            "opening_equity": 100000,
            "opening_date": "2026-07-10",
        },
    )
    client.post(
        "/api/positions",
        json={
            "bucket": "core",
            "symbol": "BRK.B",
            "asset_type": "equity",
            "quantity": 1,
            "entry_price": 500,
            "opened_on": "2026-07-10",
        },
    )
    client.post(
        "/api/wheel/puts",
        json={
            "trade_date": "2026-07-10",
            "expiration": "2026-08-14",
            "strike": 60,
            "premium": 1,
            "quantity": 1,
            "fees": 0,
        },
    )
    client.post(
        "/api/exit-positions",
        json={
            "name": "Legacy stock",
            "position_type": "stock",
            "current_value": 5000,
            "target_value": 8000,
        },
    )
    client.post(
        "/api/profit-ledger/realized",
        json={"source": "leaps", "occurred_on": "2026-07-10", "amount": 500},
    )


def test_reset_rejects_incorrect_confirmation_and_preserves_data() -> None:
    client, _ = reset_client()
    seed_data(client)

    response = client.post("/api/system/reset", json={"confirmation": "reset"})

    assert response.status_code == 422
    assert client.get("/api/portfolio/summary").json()["initialized"] is True
    app.dependency_overrides.clear()


def test_reset_clears_all_business_data_in_one_operation() -> None:
    client, sessions = reset_client()
    seed_data(client)
    with sessions() as session:
        WheelPortfolioService(session).open_put(
            batch_number=1,
            trade_date=date(2026, 7, 18),
            expiration=date(2026, 8, 21),
            strike=Decimal("50"),
            premium=Decimal("1.50"),
            quantity=1,
            entry_tqqq_price=Decimal("55"),
        )
        session.add(
            OtherHoldingRecord(
                symbol="AAPL",
                quantity=Decimal("10"),
                current_price=Decimal("225"),
            )
        )
        session.add(
            RealizedCashPosting(
                source_key="test-reset-posting",
                source_bucket="leaps",
                posted_bucket="cash",
                amount=Decimal("300"),
                occurred_on=date(2026, 7, 18),
            )
        )
        session.add(
            BrokerImportRecord(
                fingerprint="a" * 64,
                filename="activity.csv",
                section="Open Positions",
                row_index=1,
                action="create_position",
                entity_type="position",
                entity_id=1,
                raw={"Symbol": "BRK B"},
            )
        )
        session.commit()

    response = client.post("/api/system/reset", json={"confirmation": "RESET"})

    assert response.status_code == 200
    assert response.json()["status"] == "reset"
    assert client.get("/api/portfolio/summary").json() == {"initialized": False}
    assert client.get("/api/positions").json() == []
    assert client.get("/api/ledger/events").json() == []
    assert client.get("/api/signals").json() == []
    assert client.get("/api/wheel/current").json() == {"state": "waiting_put"}
    assert client.get("/api/exit-positions").json()["records"] == []
    with sessions() as session:
        assert session.query(WheelCallLot).count() == 0
        assert session.query(WheelShareLot).count() == 0
        assert session.query(WheelPutLot).count() == 0
        assert session.query(WheelRound).count() == 0
        assert session.query(ProfitLedgerEntry).count() == 0
        assert session.query(OtherHoldingRecord).count() == 0
        assert session.query(RealizedCashPosting).count() == 0
        assert session.query(BrokerImportRecord).count() == 0
    app.dependency_overrides.clear()
