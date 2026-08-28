import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")
SHARE = Decimal("0.0001")
SOFT_BAND = Decimal("0.05")
HARD_BAND = Decimal("0.10")


@dataclass(frozen=True)
class ReviewSchedule:
    next_review_on: date
    due: bool


@dataclass(frozen=True)
class CoreRebalanceDecision:
    code: str
    actionable: bool
    target_after_sale: Decimal
    sell_amount: Decimal
    estimated_shares: Decimal
    symbol: str


def review_schedule(
    opening_date: date, last_rebalanced_on: date | None, as_of: date
) -> ReviewSchedule:
    next_review = _add_months(last_rebalanced_on or opening_date, 6)
    return ReviewSchedule(next_review_on=next_review, due=as_of >= next_review)


def evaluate_core_rebalance(
    target_fraction: Decimal,
    actual_fraction: Decimal,
    review_due: bool,
    total_equity: Decimal,
    share_price: Decimal,
    symbol: str = "BRK.B",
) -> CoreRebalanceDecision:
    deviation = actual_fraction - target_fraction
    target_after_sale = target_fraction + SOFT_BAND
    if deviation <= ZERO:
        code = "underweight"
    elif deviation <= SOFT_BAND:
        code = "pause"
    elif deviation <= HARD_BAND or not review_due:
        code = "observe"
    else:
        code = "sell"
    sell_amount = (
        max(total_equity * (actual_fraction - target_after_sale), ZERO).quantize(CENT)
        if code == "sell"
        else ZERO
    )
    estimated_shares = (
        (sell_amount / share_price).quantize(SHARE)
        if sell_amount > ZERO and share_price > ZERO
        else ZERO
    )
    return CoreRebalanceDecision(
        code=code,
        actionable=code == "sell" and estimated_shares > ZERO,
        target_after_sale=target_after_sale,
        sell_amount=sell_amount,
        estimated_shares=estimated_shares,
        symbol=symbol,
    )


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
