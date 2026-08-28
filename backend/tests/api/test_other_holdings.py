from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base
from app.main import app


@contextmanager
def other_client():
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
        json={
            "age": 36,
            "opening_equity": 100000,
            "opening_date": "2026-07-22",
        },
    )
    assert response.status_code == 201


def test_other_holdings_are_simple_unique_symbol_quantity_records() -> None:
    with other_client() as client:
        initialize(client)
        created = client.post(
            "/api/other-holdings", json={"symbol": "aapl", "quantity": 10}
        )

        assert created.status_code == 201
        assert created.json()["symbol"] == "AAPL"
        assert created.json()["quantity"] == 10
        assert created.json()["current_price"] is None
        assert created.json()["current_value"] is None

        duplicate = client.post(
            "/api/other-holdings", json={"symbol": "AAPL", "quantity": 2}
        )
        assert duplicate.status_code == 409

        updated = client.patch(
            f"/api/other-holdings/{created.json()['id']}", json={"quantity": 7.5}
        )
        assert updated.status_code == 200
        assert updated.json()["quantity"] == 7.5

        listing = client.get("/api/other-holdings").json()
        assert listing["total_value"] == 0.0
        assert listing["unpriced_count"] == 1
        assert len(listing["records"]) == 1

        deleted = client.delete(f"/api/other-holdings/{created.json()['id']}")
        assert deleted.status_code == 204
        assert client.get("/api/other-holdings").json()["records"] == []


def test_other_holdings_require_an_initialized_account() -> None:
    with other_client() as client:
        response = client.post(
            "/api/other-holdings", json={"symbol": "AAPL", "quantity": 10}
        )

        assert response.status_code == 409
