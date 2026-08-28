from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")


@dataclass(frozen=True)
class StrategyCapacity:
    assigned: Decimal
    committed: Decimal
    available: Decimal
    cash_occupancy: Decimal


@dataclass(frozen=True)
class CashCapacity:
    total: Decimal
    cash_equivalent: Decimal
    liquid: Decimal
    occupied: Decimal
    available: Decimal
    margin_shortfall: Decimal


@dataclass(frozen=True)
class LossResult:
    strategy_after: Decimal
    cash_after: Decimal
    strategy_loss: Decimal
    cash_loss: Decimal
    uncovered: Decimal


def strategy_capacity(assigned: Decimal, committed: Decimal) -> StrategyCapacity:
    assigned = max(assigned, ZERO).quantize(CENT)
    committed = max(committed, ZERO).quantize(CENT)
    return StrategyCapacity(
        assigned=assigned,
        committed=committed,
        available=max(assigned - committed, ZERO).quantize(CENT),
        cash_occupancy=max(committed - assigned, ZERO).quantize(CENT),
    )


def cash_capacity(
    total: Decimal,
    *,
    cash_equivalent: Decimal = ZERO,
    wheel_occupancy: Decimal = ZERO,
    leaps_occupancy: Decimal = ZERO,
) -> CashCapacity:
    total = max(total, ZERO).quantize(CENT)
    cash_equivalent = max(cash_equivalent, ZERO).quantize(CENT)
    liquid = max(total - cash_equivalent, ZERO).quantize(CENT)
    occupied = (max(wheel_occupancy, ZERO) + max(leaps_occupancy, ZERO)).quantize(
        CENT
    )
    return CashCapacity(
        total=total,
        cash_equivalent=cash_equivalent,
        liquid=liquid,
        occupied=occupied,
        available=max(liquid - occupied, ZERO).quantize(CENT),
        margin_shortfall=max(occupied - liquid, ZERO).quantize(CENT),
    )


def apply_loss(strategy: Decimal, cash: Decimal, loss: Decimal) -> LossResult:
    strategy = max(strategy, ZERO)
    cash = max(cash, ZERO)
    remaining = max(loss, ZERO)
    strategy_loss = min(strategy, remaining)
    remaining -= strategy_loss
    cash_loss = min(cash, remaining)
    remaining -= cash_loss
    return LossResult(
        strategy_after=(strategy - strategy_loss).quantize(CENT),
        cash_after=(cash - cash_loss).quantize(CENT),
        strategy_loss=strategy_loss.quantize(CENT),
        cash_loss=cash_loss.quantize(CENT),
        uncovered=remaining.quantize(CENT),
    )
