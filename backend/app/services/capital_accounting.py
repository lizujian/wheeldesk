from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import (
    BucketBalance,
    PositionRecord,
    WheelPutLot,
    WheelShareLot,
    UnmanagedPositionRecord,
)
from app.domain.capital import CashCapacity, StrategyCapacity, cash_capacity, strategy_capacity
from app.domain.models import Bucket

ZERO = Decimal("0")


@dataclass(frozen=True)
class CapitalSnapshot:
    core: StrategyCapacity
    wheel: StrategyCapacity
    leaps: StrategyCapacity
    options: StrategyCapacity
    cash: CashCapacity

    def payload(self) -> dict:
        return {
            "core": _strategy_payload(self.core),
            "wheel": _strategy_payload(self.wheel),
            "leaps": _strategy_payload(self.leaps),
            "options": _strategy_payload(self.options),
            "cash": {
                "total": self.cash.total,
                "cash_equivalent": self.cash.cash_equivalent,
                "liquid": self.cash.liquid,
                "occupied": self.cash.occupied,
                "available": self.cash.available,
                "margin_shortfall": self.cash.margin_shortfall,
            },
        }


class CapitalAccountingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def snapshot(self) -> CapitalSnapshot:
        balances = {
            row.bucket: row.amount
            for row in self.session.scalars(select(BucketBalance))
        }
        positions = list(
            self.session.scalars(
                select(PositionRecord).where(PositionRecord.status == "open")
            )
        )
        core_commitment = sum(
            (
                row.entry_price * row.quantity * row.multiplier
                for row in positions
                if row.bucket == Bucket.CORE.value
            ),
            ZERO,
        )
        leaps_commitment = sum(
            (
                row.entry_price * row.quantity * row.multiplier
                for row in positions
                if row.bucket == Bucket.LEAPS.value
            ),
            ZERO,
        )
        put_commitment = sum(
            (
                row.collateral
                for row in self.session.scalars(
                    select(WheelPutLot).where(
                        WheelPutLot.state == "open",
                        WheelPutLot.open_quantity > 0,
                    )
                )
            ),
            ZERO,
        )
        share_commitment = sum(
            (
                row.capital
                for row in self.session.scalars(
                    select(WheelShareLot).where(
                        WheelShareLot.state == "held",
                        WheelShareLot.remaining_quantity > 0,
                    )
                )
            ),
            ZERO,
        )
        core = strategy_capacity(
            balances.get(Bucket.CORE.value, ZERO), core_commitment
        )
        wheel = strategy_capacity(
            balances.get(Bucket.WHEEL.value, ZERO),
            put_commitment + share_commitment,
        )
        leaps = strategy_capacity(
            balances.get(Bucket.LEAPS.value, ZERO), leaps_commitment
        )
        options = strategy_capacity(
            wheel.assigned + leaps.assigned,
            wheel.committed + leaps.committed,
        )
        cash = cash_capacity(
            balances.get(Bucket.CASH.value, ZERO),
            cash_equivalent=self._cash_equivalent_value(),
            wheel_occupancy=options.cash_occupancy,
        )
        return CapitalSnapshot(
            core=core,
            wheel=wheel,
            leaps=leaps,
            options=options,
            cash=cash,
        )

    def _cash_equivalent_value(self) -> Decimal:
        return sum(
            (
                (row.current_price or row.entry_price or ZERO)
                * row.quantity
                * row.multiplier
                for row in self.session.scalars(
                    select(UnmanagedPositionRecord).where(
                        UnmanagedPositionRecord.status == "open",
                        UnmanagedPositionRecord.category == "cash_equivalent",
                        UnmanagedPositionRecord.direction == "long",
                    )
                )
            ),
            ZERO,
        ).quantize(Decimal("0.01"))

    def deployments(self) -> dict[str, Decimal]:
        positions = list(
            self.session.scalars(
                select(PositionRecord).where(PositionRecord.status == "open")
            )
        )
        capital = self.snapshot()
        cash = self.session.get(BucketBalance, Bucket.CASH.value)
        wheel_deployment = capital.wheel.committed
        leaps_deployment = sum(
            (
                row.current_price * row.quantity * row.multiplier
                for row in positions
                if row.bucket == Bucket.LEAPS.value
            ),
            ZERO,
        ).quantize(Decimal("0.01"))
        return {
            Bucket.CORE.value: sum(
                (
                    row.current_price * row.quantity * row.multiplier
                    for row in positions
                    if row.bucket == Bucket.CORE.value
                ),
                ZERO,
            ).quantize(Decimal("0.01")),
            Bucket.CASH.value: (cash.amount if cash is not None else ZERO).quantize(
                Decimal("0.01")
            ),
            Bucket.WHEEL.value: wheel_deployment,
            Bucket.LEAPS.value: leaps_deployment,
            "options": (wheel_deployment + leaps_deployment).quantize(
                Decimal("0.01")
            ),
        }


def _strategy_payload(value: StrategyCapacity) -> dict:
    return {
        "assigned": value.assigned,
        "committed": value.committed,
        "available": value.available,
        "cash_occupancy": value.cash_occupancy,
    }
