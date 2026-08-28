from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db_models import Base
from app.domain.models import Bucket
from app.services.ledger import LedgerService


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def test_ledger_reversal_preserves_original_event(session: Session) -> None:
    service = LedgerService(session)
    original = service.record(
        event_type="deposit",
        bucket=Bucket.UNALLOCATED,
        amount=Decimal("10000"),
        occurred_on=date(2026, 7, 10),
        details={"note": "新增资金"},
    )

    reversal = service.reverse(original.id, occurred_on=date(2026, 7, 11), note="录入错误")

    session.refresh(original)
    assert original.amount == Decimal("10000.00")
    assert reversal.amount == Decimal("-10000.00")
    assert reversal.reverses_event_id == original.id
    assert service.bucket_cash(Bucket.UNALLOCATED) == Decimal("0.00")


def test_event_cannot_be_reversed_twice(session: Session) -> None:
    service = LedgerService(session)
    original = service.record(
        event_type="deposit",
        bucket=Bucket.UNALLOCATED,
        amount=Decimal("100"),
        occurred_on=date(2026, 7, 10),
    )
    service.reverse(original.id, date(2026, 7, 11), "first")

    with pytest.raises(ValueError, match="已经冲销"):
        service.reverse(original.id, date(2026, 7, 12), "second")

