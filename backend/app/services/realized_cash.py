from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db_models import (
    BucketBalance,
    LedgerEvent,
    ProfitLedgerEntry,
    RealizedCashPosting,
)
from app.domain.models import Bucket
from app.domain.capital import apply_loss

ZERO = Decimal("0")


class RealizedCashService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def post(
        self,
        source_key: str,
        source_bucket: Bucket,
        amount: Decimal,
        occurred_on: date,
        *,
        profit_source: str | None = None,
        note: str = "",
    ) -> RealizedCashPosting | None:
        if amount == ZERO:
            return None
        existing = self.session.scalar(
            select(RealizedCashPosting).where(
                RealizedCashPosting.source_key == source_key
            )
        )
        if existing is not None:
            return existing
        posted_bucket = Bucket.CASH if amount > ZERO else source_bucket
        strategy_loss = ZERO
        peer_loss = ZERO
        peer_bucket: Bucket | None = None
        cash_loss = ZERO
        if amount > ZERO:
            balance = self._balance(Bucket.CASH)
            balance.amount += amount
        elif source_bucket == Bucket.CASH:
            cash_loss = -amount
            self._balance(Bucket.CASH).amount -= cash_loss
        elif source_bucket in {Bucket.WHEEL, Bucket.LEAPS}:
            peer_bucket = (
                Bucket.LEAPS if source_bucket == Bucket.WHEEL else Bucket.WHEEL
            )
            source_balance = self._balance(source_bucket)
            peer_balance = self._balance(peer_bucket)
            cash_balance = self._balance(Bucket.CASH)
            remaining = -amount
            strategy_loss = min(source_balance.amount, remaining)
            source_balance.amount -= strategy_loss
            remaining -= strategy_loss
            peer_loss = min(peer_balance.amount, remaining)
            peer_balance.amount -= peer_loss
            remaining -= peer_loss
            cash_loss = remaining
            cash_balance.amount -= remaining
        else:
            source_balance = self._balance(source_bucket)
            cash_balance = self._balance(Bucket.CASH)
            result = apply_loss(source_balance.amount, cash_balance.amount, -amount)
            source_balance.amount = result.strategy_after
            cash_balance.amount = result.cash_after - result.uncovered
            strategy_loss = result.strategy_loss
            cash_loss = result.cash_loss + result.uncovered
        posting = RealizedCashPosting(
            source_key=source_key,
            source_bucket=source_bucket.value,
            posted_bucket=posted_bucket.value,
            amount=amount,
            occurred_on=occurred_on,
        )
        self.session.add(posting)
        self.session.add(
            LedgerEvent(
                event_type=(
                    "realized_profit_to_cash" if amount > ZERO else "realized_loss"
                ),
                bucket=posted_bucket.value,
                amount=amount,
                occurred_on=occurred_on,
                details={
                    "source_key": source_key,
                    "source": source_bucket.value,
                    "strategy_loss": float(strategy_loss),
                    "peer_loss": float(peer_loss),
                    "peer_bucket": peer_bucket.value if peer_bucket else None,
                    "cash_loss": float(cash_loss),
                },
            )
        )
        if profit_source is not None:
            self.session.add(
                ProfitLedgerEntry(
                    entry_type="realized",
                    source=profit_source,
                    amount=amount,
                    occurred_on=occurred_on,
                    note=note,
                    details={"automatic": True, "source_key": source_key},
                )
            )
        return posting

    def reverse(self, source_key: str, occurred_on: date, reason: str) -> bool:
        posting = self.session.scalar(
            select(RealizedCashPosting).where(
                RealizedCashPosting.source_key == source_key
            )
        )
        if posting is None:
            return False
        loss_event = self.session.scalar(
            select(LedgerEvent)
            .where(
                LedgerEvent.event_type == "realized_loss",
                LedgerEvent.details["source_key"].as_string() == source_key,
            )
            .order_by(LedgerEvent.id.desc())
        )
        if posting.amount < ZERO and loss_event is not None:
            strategy_loss = Decimal(str(loss_event.details.get("strategy_loss", 0)))
            peer_loss = Decimal(str(loss_event.details.get("peer_loss", 0)))
            peer_bucket = loss_event.details.get("peer_bucket")
            cash_loss = Decimal(str(loss_event.details.get("cash_loss", 0)))
            if posting.source_bucket == Bucket.CASH.value:
                self._balance(Bucket.CASH).amount += cash_loss
            else:
                self._balance(Bucket(posting.source_bucket)).amount += strategy_loss
                if peer_bucket and peer_loss:
                    self._balance(Bucket(peer_bucket)).amount += peer_loss
                self._balance(Bucket.CASH).amount += cash_loss
        else:
            balance = self.session.get(BucketBalance, posting.posted_bucket)
            if balance is not None:
                balance.amount -= posting.amount
        self.session.add(
            LedgerEvent(
                event_type="realized_posting_reversal",
                bucket=posting.posted_bucket,
                amount=-posting.amount,
                occurred_on=occurred_on,
                details={"source_key": source_key, "reason": reason},
            )
        )
        self.session.execute(
            delete(ProfitLedgerEntry).where(
                ProfitLedgerEntry.details["source_key"].as_string() == source_key
            )
        )
        self.session.delete(posting)
        return True

    def _balance(self, bucket: Bucket) -> BucketBalance:
        balance = self.session.get(BucketBalance, bucket.value)
        if balance is None:
            balance = BucketBalance(bucket=bucket.value, amount=ZERO)
            self.session.add(balance)
        return balance
