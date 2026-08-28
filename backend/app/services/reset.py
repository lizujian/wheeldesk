from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db_models import (
    BrokerImportRecord,
    BucketBalance,
    ExitPositionRecord,
    LedgerEvent,
    OtherHoldingRecord,
    PortfolioProfile,
    PositionRecord,
    ProfitLedgerEntry,
    RealizedCashPosting,
    SignalRecord,
    UnmanagedPositionRecord,
    WheelCallLot,
    WheelCycle,
    WheelPutLot,
    WheelRound,
    WheelShareLot,
)


class ResetService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def reset_all(self) -> None:
        try:
            for model in (
                BrokerImportRecord,
                RealizedCashPosting,
                ProfitLedgerEntry,
                WheelCallLot,
                WheelShareLot,
                WheelPutLot,
                WheelRound,
                LedgerEvent,
                UnmanagedPositionRecord,
                OtherHoldingRecord,
                ExitPositionRecord,
                SignalRecord,
                PositionRecord,
                BucketBalance,
                PortfolioProfile,
                WheelCycle,
            ):
                self.session.execute(delete(model))
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
