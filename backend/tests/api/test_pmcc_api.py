from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base, UnmanagedPositionRecord
from app.main import app


@contextmanager
def pmcc_client():
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
        yield TestClient(app), sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_summary_and_other_holdings_expose_one_linked_pmcc_state() -> None:
    with pmcc_client() as (client, sessions):
        initialized = client.post(
            "/api/portfolio/initialize",
            json={
                "age": 36,
                "opening_equity": 100000,
                "opening_date": "2026-09-01",
            },
        )
        assert initialized.status_code == 201

        long = client.post(
            "/api/positions",
            json={
                "bucket": "leaps",
                "symbol": "QQQ",
                "asset_type": "option",
                "direction": "long",
                "option_type": "call",
                "quantity": 1,
                "entry_price": 100,
                "opened_on": "2026-09-23",
                "expiration": "2027-09-23",
                "strike": 450,
                "tranche": 1,
            },
        )
        assert long.status_code == 201, long.text

        short = client.post(
            "/api/other-holdings",
            json={
                "symbol": "QQQ",
                "quantity": 1,
                "asset_type": "option",
                "direction": "short",
                "option_type": "call",
                "entry_price": 5,
                "current_price": 2,
                "opened_on": "2026-09-23",
                "expiration": "2026-10-23",
                "strike": 530,
            },
        )
        assert short.status_code == 201, short.text

        with sessions() as session:
            record = session.get(UnmanagedPositionRecord, short.json()["id"])
            assert record is not None
            record.category = "pmcc"
            record.linked_position_id = long.json()["id"]
            session.commit()

        summary = client.get("/api/portfolio/summary")
        assert summary.status_code == 200, summary.text
        pmcc = summary.json()["capital"]["pmcc"]
        assert pmcc["qqq"]["committed"] == 10000
        assert pmcc["total"]["net_cash_flow"] == 300
        assert pmcc["states"][0]["status"] == "covered"
        assert pmcc["states"][0]["coverage_ratio"] == 1

        listing = client.get("/api/other-holdings?include_closed=true")
        assert listing.status_code == 200, listing.text
        payload = listing.json()
        assert payload["pmcc"]["states"][0]["status"] == "covered"
        assert payload["leaps_call_wheels"][0]["pmcc_state"]["long_position_id"] == long.json()["id"]
