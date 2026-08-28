from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base
from app.main import app


@contextmanager
def transfer_client():
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


def initialize(client: TestClient) -> None:
    response = client.post(
        "/api/portfolio/initialize",
        json={"age": 36, "opening_equity": 100000, "opening_date": "2026-08-01"},
    )
    assert response.status_code == 201, response.text


def test_internal_option_transfer_does_not_change_shared_capacity() -> None:
    with transfer_client() as client:
        initialize(client)
        opened = client.post(
            "/api/wheel/portfolio/puts",
            json={
                "batch_number": 1,
                "trade_date": "2026-08-03",
                "expiration": "2026-09-11",
                "strike": 100,
                "premium": 2,
                "quantity": 1,
                "entry_tqqq_price": 110,
            },
        )
        assert opened.status_code == 201, opened.text

        accepted = client.post(
            "/api/portfolio/transfers",
            json={
                "source": "wheel",
                "target": "leaps",
                "amount": 14000,
                "date": "2026-08-10",
                "note": "策略过渡",
            },
        )

        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["balances"]["wheel"] == 0.0
        assert accepted.json()["balances"]["leaps"] == 39000.0
        assert accepted.json()["capital"]["options"] == {
            "assigned": 39000.0,
            "committed": 10000.0,
            "available": 29000.0,
            "cash_occupancy": 0.0,
        }
