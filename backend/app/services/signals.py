from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import SignalRecord

SEVERITY_ORDER = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}


class SignalService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def emit(
        self,
        code: str,
        title: str,
        message: str,
        severity: str,
        market_date: date,
        stale: bool = False,
        formal: bool = True,
    ) -> SignalRecord | None:
        if severity not in SEVERITY_ORDER:
            raise ValueError("未知的信号级别")
        if stale and formal:
            return None
        existing = self.session.scalar(
            select(SignalRecord).where(
                SignalRecord.code == code,
                SignalRecord.market_date == market_date,
            )
        )
        if existing is not None:
            return existing
        signal = SignalRecord(
            code=code,
            title=title,
            message=message,
            severity=severity,
            market_date=market_date,
        )
        self.session.add(signal)
        self.session.commit()
        return signal

    def list_active(self) -> list[SignalRecord]:
        return self.list_recent(include_acknowledged=False)

    def list_recent(
        self,
        *,
        include_acknowledged: bool = False,
        limit: int = 100,
    ) -> list[SignalRecord]:
        query = select(SignalRecord)
        if not include_acknowledged:
            query = query.where(SignalRecord.acknowledged.is_(False))
        records = list(self.session.scalars(query))
        return sorted(
            records,
            key=lambda signal: (
                signal.acknowledged,
                SEVERITY_ORDER[signal.severity] if not signal.acknowledged else 0,
                -signal.market_date.toordinal(),
                -signal.id,
            ),
        )[:limit]

    def acknowledge(self, signal_id: int) -> SignalRecord:
        signal = self.session.get(SignalRecord, signal_id)
        if signal is None:
            raise ValueError("找不到信号")
        signal.acknowledged = True
        self.session.commit()
        return signal
