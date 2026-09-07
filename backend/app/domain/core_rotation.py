from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_DOWN

ZERO = Decimal("0")


@dataclass(frozen=True)
class RotationRules:
    min_brk_weight: Decimal = Decimal("0.30")
    max_brk_weight: Decimal = Decimal("1.00")
    confirmation_sessions: int = 3
    window_sessions: int = 20
    max_turnover: Decimal = Decimal("0.20")
    tolerance: Decimal = Decimal("0.02")
    sell_bands: tuple = ((Decimal("0.88"), Decimal("0.30")), (Decimal("0.83"), Decimal("0.55")), (Decimal("0.78"), Decimal("0.80")))
    buy_bands: tuple = ((Decimal("0.65"), Decimal("1.00")), (Decimal("0.68"), Decimal("0.85")), (Decimal("0.72"), Decimal("0.70")))


RULES = RotationRules()


@dataclass(frozen=True)
class RotationUsage:
    used_weight: Decimal = ZERO
    complete: bool = True


@dataclass(frozen=True)
class CoreRotationDecision:
    code: str = "waiting"
    actionable: bool = False
    ratio: Decimal | None = None
    ratio_as_of: date | None = None
    band: str | None = None
    confirmation_days: int = 0
    current_brk_weight: Decimal = ZERO
    projected_brk_weight: Decimal = ZERO
    target_brk_weight: Decimal = ZERO
    next_brk_weight: Decimal = ZERO
    weight_change: Decimal = ZERO
    used_weight: Decimal = ZERO
    remaining_weight: Decimal = RULES.max_turnover
    sell_symbol: str | None = None
    buy_symbol: str | None = None
    amount: Decimal = ZERO
    sell_shares: Decimal = ZERO
    buy_shares: Decimal = ZERO


def ratio_band(ratio: Decimal, rules: RotationRules = RULES):
    for threshold, target in rules.sell_bands:
        if ratio >= threshold:
            return "BRK.B", target, f"sell_{threshold}"
    for threshold, target in rules.buy_bands:
        if ratio <= threshold:
            return "VOO", target, f"buy_{threshold}"
    return None


def evaluate_rotation(
    *,
    full: bool,
    brk_value: Decimal,
    voo_value: Decimal,
    brk_price: Decimal,
    voo_price: Decimal,
    ratios: list[tuple[date, Decimal]],
    pending_brk_shares: Decimal = ZERO,
    pending_voo_shares: Decimal = ZERO,
    usage: RotationUsage = RotationUsage(),
    data_valid: bool = True,
    daily_limit_open: bool = True,
    rules: RotationRules = RULES,
) -> CoreRotationDecision:
    numbers = (brk_value, voo_value, brk_price, voo_price, pending_brk_shares, pending_voo_shares)
    if any(not number.is_finite() or number < ZERO for number in numbers) or any(
        not ratio.is_finite() or ratio <= ZERO for _, ratio in ratios
    ):
        return CoreRotationDecision(code="invalid_data")
    total = brk_value + voo_value
    weight = brk_value / total if total > ZERO else ZERO
    projected_brk = brk_value + pending_brk_shares * brk_price
    projected_total = total + pending_brk_shares * brk_price + pending_voo_shares * voo_price
    decision = CoreRotationDecision(
        current_brk_weight=weight, target_brk_weight=weight, next_brk_weight=weight,
        projected_brk_weight=projected_brk / projected_total if projected_total > ZERO else ZERO,
        used_weight=usage.used_weight,
        remaining_weight=max(rules.max_turnover - usage.used_weight, ZERO),
        ratio=ratios[-1][1] if ratios else None,
        ratio_as_of=ratios[-1][0] if ratios else None,
    )
    if not full or total <= ZERO:
        return decision
    if not data_valid or len(ratios) < rules.confirmation_sessions or min(brk_price, voo_price) <= ZERO:
        return replace(decision, code="invalid_data")
    band = ratio_band(ratios[-1][1], rules)
    if band is None:
        return replace(decision, code="neutral")
    sell_symbol, target, band_code = band
    target = min(max(target, rules.min_brk_weight), rules.max_brk_weight)
    confirmation = 0
    for _, ratio in reversed(ratios):
        # A more extreme close also confirms a less extreme threshold.
        matched = ratio_band(ratio, rules)
        if matched is None or matched[0] != sell_symbol:
            break
        if (sell_symbol == "BRK.B" and matched[1] > target) or (sell_symbol == "VOO" and matched[1] < target):
            break
        confirmation += 1
    delta = weight - target if sell_symbol == "BRK.B" else target - weight
    decision = replace(decision, band=band_code, target_brk_weight=target, confirmation_days=confirmation)
    if delta <= rules.tolerance:
        return replace(decision, code="within_target")
    decision = replace(decision, sell_symbol=sell_symbol, buy_symbol="VOO" if sell_symbol == "BRK.B" else "BRK.B")
    if confirmation < rules.confirmation_sessions:
        return replace(decision, code="confirming")
    if (sell_symbol == "BRK.B" and pending_brk_shares > ZERO) or (sell_symbol == "VOO" and pending_voo_shares > ZERO):
        return replace(decision, code="pending_puts")
    if not usage.complete:
        return replace(decision, code="execution_unverified")
    if not daily_limit_open:
        return replace(decision, code="daily_limit")
    if decision.remaining_weight <= ZERO:
        return replace(decision, code="window_limit")
    change = min(delta, decision.remaining_weight)
    next_weight = weight - change if sell_symbol == "BRK.B" else weight + change
    if not rules.min_brk_weight <= next_weight <= rules.max_brk_weight:
        return replace(decision, code="weight_constraint")
    amount = (total * change).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    change = amount / total
    return replace(
        decision, code="opportunity", actionable=amount > ZERO, amount=amount,
        weight_change=change, next_brk_weight=weight - change if sell_symbol == "BRK.B" else weight + change,
        sell_shares=(amount / (brk_price if sell_symbol == "BRK.B" else voo_price)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN),
        buy_shares=(amount / (voo_price if sell_symbol == "BRK.B" else brk_price)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN),
    )
