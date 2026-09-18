from dataclasses import dataclass
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")
LEAPS_CALL_WHEEL_CATEGORY = "leaps_call_wheel"


@dataclass(frozen=True)
class LeapsMarketState:
    close: Decimal
    previous_close: Decimal
    ma20: Decimal
    previous_ma20: Decimal
    ma200: Decimal
    drawdown: Decimal
    rsi14: Decimal
    previous_rsi14: Decimal
    previous_above_ma20: bool
    two_closes_above_ma20: bool
    current_price: Decimal | None = None
    current_change_fraction: Decimal | None = None
    session_quote_live: bool = False


@dataclass(frozen=True)
class LeapsTrancheDecision:
    tranche: int
    eligible: bool
    allocation_fraction: Decimal
    suggested_amount: Decimal
    checks: dict[str, bool]


@dataclass(frozen=True)
class LeapsExitInputs:
    opened_on: date
    expiration: date
    as_of: date
    entry_price: Decimal
    current_bid: Decimal | None


@dataclass(frozen=True)
class LeapsExitDecision:
    code: str
    actionable: bool
    days_held: int
    dte: int | None
    return_fraction: Decimal | None
    target_return: Decimal | None


def evaluate_leaps_tranches(
    market: LeapsMarketState,
    used_tranches: set[int],
    bucket_current: Decimal,
    bucket_target: Decimal,
    *,
    as_of: date,
    last_entry_date: date | None,
    shared_current: Decimal | None = None,
    shared_target: Decimal | None = None,
) -> list[LeapsTrancheDecision]:
    capacity = max(
        (shared_target if shared_target is not None else bucket_target)
        - (shared_current if shared_current is not None else bucket_current),
        ZERO,
    )
    available_tranches = [value for value in range(1, 6) if value not in used_tranches]
    next_tranche = available_tranches[0] if available_tranches else None
    daily_limit = last_entry_date != as_of
    current_change = market.current_change_fraction
    if current_change is None and market.current_price is not None and market.close > ZERO:
        current_change = (market.current_price - market.close) / market.close
    fractions = [Decimal("0.20")] * 5
    decisions: list[LeapsTrancheDecision] = []
    for tranche, fraction in enumerate(fractions, start=1):
        checks = {
            "above_ma200": market.close > market.ma200,
            "rsi_below_45": market.rsi14 < Decimal("45"),
            "daily_drop": current_change is not None
            and current_change < Decimal("-0.01"),
            "live_quote": market.session_quote_live,
            "daily_limit": daily_limit,
            "next_slot": tranche == next_tranche,
        }
        eligible = capacity > ZERO and tranche not in used_tranches and all(checks.values())
        amount = min(bucket_target * fraction, capacity) if eligible else ZERO
        decisions.append(
            LeapsTrancheDecision(
                tranche=tranche,
                eligible=eligible,
                allocation_fraction=fraction,
                suggested_amount=amount.quantize(Decimal("0.01")) if amount else ZERO,
                checks=checks,
            )
        )
    return decisions


def select_fifo_position(
    positions: list[tuple[int, int, date]],
) -> dict[str, int | date] | None:
    if not positions:
        return None
    position_id, slot, opened_on = min(
        positions,
        key=lambda value: (value[2], value[0]),
    )
    return {
        "position_id": position_id,
        "slot": slot,
        "opened_on": opened_on,
    }


def validate_leaps_contract(
    symbol: str,
    option_type: str,
    direction: str,
    dte: int,
    delta: Decimal | None = None,
) -> None:
    if symbol.upper() == "TQQQ":
        raise ValueError("LEAPS 禁止使用 TQQQ")
    if option_type.lower() != "call" or direction.lower() != "long":
        raise ValueError("LEAPS 必须是买入 Long Call")
    if dte <= 0:
        raise ValueError("LEAPS 到期日必须晚于开仓日期")


def evaluate_leaps_exit(inputs: LeapsExitInputs) -> LeapsExitDecision:
    days_held = max((inputs.as_of - inputs.opened_on).days, 0)
    dte = max((inputs.expiration - inputs.as_of).days, 0)
    if days_held > 270:
        return LeapsExitDecision(
            "force_exit", True, days_held, dte, _return_fraction(inputs), None
        )

    target = _option_profit_target(days_held)
    current_return = _return_fraction(inputs)
    if current_return is None:
        return LeapsExitDecision(
            "quote_unavailable", False, days_held, dte, None, target
        )
    return LeapsExitDecision(
        "take_profit" if current_return >= target else "hold",
        current_return >= target,
        days_held,
        dte,
        current_return,
        target,
    )


def evaluate_leaps_equity_exit(
    *,
    opened_on: date,
    as_of: date,
    entry_price: Decimal,
    current_price: Decimal,
) -> LeapsExitDecision:
    days_held = max((as_of - opened_on).days, 0)
    target = _equity_profit_target(days_held)
    current_return = (
        (current_price - entry_price) / entry_price if entry_price > ZERO else None
    )
    return LeapsExitDecision(
        "take_profit" if current_return is not None and current_return >= target else "hold",
        current_return is not None and current_return >= target,
        days_held,
        None,
        current_return,
        target,
    )


def _option_profit_target(days_held: int) -> Decimal:
    if days_held <= 120:
        return Decimal("0.50")
    if days_held <= 180:
        return Decimal("0.30")
    return Decimal("0.10")


def _equity_profit_target(days_held: int) -> Decimal:
    if days_held <= 120:
        return Decimal("0.25")
    if days_held <= 180:
        return Decimal("0.15")
    return Decimal("0.05")


def _return_fraction(inputs: LeapsExitInputs) -> Decimal | None:
    if inputs.current_bid is None or inputs.entry_price <= ZERO:
        return None
    return (inputs.current_bid - inputs.entry_price) / inputs.entry_price


def roll_priority(dte: int) -> str | None:
    if dte < 270:
        return "high"
    if dte < 365:
        return "warning"
    return None
