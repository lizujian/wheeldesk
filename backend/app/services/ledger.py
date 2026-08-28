from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db_models import LedgerEvent
from app.domain.models import Bucket


class LedgerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        event_type: str,
        bucket: Bucket,
        amount: Decimal,
        occurred_on: date,
        details: dict[str, Any] | None = None,
        wheel_cycle_id: int | None = None,
    ) -> LedgerEvent:
        event = LedgerEvent(
            event_type=event_type,
            bucket=bucket.value,
            amount=amount,
            occurred_on=occurred_on,
            details=details or {},
            wheel_cycle_id=wheel_cycle_id,
        )
        self.session.add(event)
        self.session.commit()
        return event

    def reverse(self, event_id: int, occurred_on: date, note: str) -> LedgerEvent:
        original = self.session.get(LedgerEvent, event_id)
        if original is None:
            raise ValueError("找不到需要冲销的事件")
        if original.reverses_event_id is not None:
            raise ValueError("冲销事件不能再次冲销")
        existing = self.session.scalar(
            select(LedgerEvent).where(LedgerEvent.reverses_event_id == event_id)
        )
        if existing is not None:
            raise ValueError("该事件已经冲销")
        reversal = LedgerEvent(
            event_type="reversal",
            bucket=original.bucket,
            amount=-original.amount,
            occurred_on=occurred_on,
            details={"note": note, "original_event_type": original.event_type},
            reverses_event_id=original.id,
            wheel_cycle_id=original.wheel_cycle_id,
        )
        self.session.add(reversal)
        self.session.commit()
        return reversal

    def bucket_cash(self, bucket: Bucket) -> Decimal:
        total = self.session.scalar(
            select(func.coalesce(func.sum(LedgerEvent.amount), 0)).where(
                LedgerEvent.bucket == bucket.value
            )
        )
        return Decimal(total).quantize(Decimal("0.01"))

    def list_events(self) -> list[LedgerEvent]:
        return list(
            self.session.scalars(
                select(LedgerEvent).order_by(LedgerEvent.occurred_on.desc(), LedgerEvent.id.desc())
            )
        )

