from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")


@dataclass(frozen=True)
class BatchRecommendation:
    first: Decimal
    second: Decimal


@dataclass(frozen=True)
class BudgetStatus:
    budget: Decimal
    exposure: Decimal
    available: Decimal
    over_budget: Decimal
    usage_fraction: Decimal | None


@dataclass(frozen=True)
class EarlyCloseSignal:
    code: str | None
    captured_fraction: Decimal
    actionable: bool
    message: str


def recommend_batches(budget: Decimal, exposure: Decimal) -> BatchRecommendation:
    status = budget_status(budget, exposure)
    return BatchRecommendation(
        first=min(budget * Decimal("0.60"), status.available).quantize(CENT),
        second=min(budget * Decimal("0.40"), status.available).quantize(CENT),
    )


def budget_status(budget: Decimal, exposure: Decimal) -> BudgetStatus:
    if budget < ZERO or exposure < ZERO:
        raise ValueError("预算和策略占用不能为负数")
    return BudgetStatus(
        budget=budget.quantize(CENT),
        exposure=exposure.quantize(CENT),
        available=max(budget - exposure, ZERO).quantize(CENT),
        over_budget=max(exposure - budget, ZERO).quantize(CENT),
        usage_fraction=exposure / budget if budget > ZERO else None,
    )


def calculate_exposure(
    put_collateral: Iterable[Decimal],
    assigned_share_capital: Iterable[Decimal],
) -> Decimal:
    exposure = sum(put_collateral, ZERO) + sum(assigned_share_capital, ZERO)
    if exposure < ZERO:
        raise ValueError("策略占用不能为负数")
    return exposure.quantize(CENT)


def annualized_return(
    profit: Decimal,
    collateral: Decimal,
    days: int,
) -> Decimal | None:
    if collateral <= ZERO or days <= 0:
        return None
    return (profit / collateral * Decimal("365") / Decimal(days)).quantize(
        Decimal("0.000001")
    )


def early_close_signal(
    opened_on: date,
    expiration: date,
    as_of: date,
    opening_premium: Decimal,
    reference_buyback: Decimal,
    quote_source: str,
) -> EarlyCloseSignal:
    if opening_premium <= ZERO or reference_buyback < ZERO:
        raise ValueError("期权权利金参数无效")
    captured = (opening_premium - reference_buyback) / opening_premium
    held_days = (as_of - opened_on).days
    dte = (expiration - as_of).days
    if captured >= Decimal("0.75"):
        code = "regular_profit"
    elif dte <= 21 and captured >= Decimal("0.50"):
        code = "expiry_profit"
    elif held_days <= 10 and captured >= Decimal("0.50"):
        code = "fast_profit"
    else:
        code = None
    actionable = code is not None and quote_source == "public"
    return EarlyCloseSignal(
        code=code,
        captured_fraction=captured,
        actionable=actionable,
        message=_signal_message(code, actionable),
    )


def _signal_message(code: str | None, actionable: bool) -> str:
    if code is None:
        return "尚未达到提前平仓阈值。"
    if not actionable:
        return "进入止盈区，请在券商确认实际买回价格。"
    return {
        "regular_profit": "已捕获至少 75% 权利金，建议提前平仓。",
        "expiry_profit": "已进入 21 DTE 风险区，建议提前平仓。",
        "fast_profit": "权利金短期快速衰减，建议提前平仓。",
    }[code]
