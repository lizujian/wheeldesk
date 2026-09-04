from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")
SHARE = Decimal("0.0001")

TIER_FRACTIONS = {
    "monthly": Decimal("0.10"),
    "pullback": Decimal("0.20"),
    "correction": Decimal("0.30"),
    "deep": Decimal("0.40"),
}
MONTHLY_FRACTIONS = (
    (Decimal("65"), Decimal("0.025")),
    (Decimal("50"), Decimal("0.05")),
)
TIER_RANK = {"monthly": 1, "pullback": 2, "correction": 3, "deep": 4}
CORE_SYMBOLS = ("BRK.B", "VOO")


@dataclass(frozen=True)
class CoreBuyInputs:
    as_of: date
    price: Decimal
    drawdown: Decimal
    daily_change: Decimal
    rsi14: Decimal
    vix: Decimal
    target_gap: Decimal
    available_funding: Decimal
    last_purchase_date: date | None
    last_purchase_tier: str | None
    below_ma200_two_days: bool = False


@dataclass(frozen=True)
class CoreBuyDecision:
    code: str
    actionable: bool
    fraction: Decimal
    strategy_amount: Decimal
    executable_amount: Decimal
    funding_required: Decimal
    shares: Decimal
    signal_score: int
    trend_reduced: bool


@dataclass(frozen=True)
class CoreAssetInputs:
    symbol: str
    current_value: Decimal
    price: Decimal
    drawdown: Decimal
    daily_change: Decimal
    rsi14: Decimal
    ma200: Decimal
    below_ma200_two_days: bool
    return_20d: Decimal
    return_126d: Decimal
    last_purchase_date: date | None
    last_purchase_tier: str | None


@dataclass(frozen=True)
class CoreAssetDecision:
    symbol: str
    current_value: Decimal
    price: Decimal
    drawdown: Decimal
    daily_change: Decimal
    rsi14: Decimal
    ma200: Decimal
    below_ma200_two_days: bool
    return_20d: Decimal
    return_126d: Decimal
    code: str
    actionable: bool
    fraction: Decimal
    strategy_amount: Decimal
    executable_amount: Decimal
    funding_required: Decimal
    shares: Decimal
    signal_score: int
    trend_reduced: bool


@dataclass(frozen=True)
class CoreRotationDecision:
    code: str
    actionable: bool
    sell_symbol: str | None
    buy_symbol: str | None
    amount: Decimal
    sell_shares: Decimal
    buy_shares: Decimal
    return_spread: Decimal
    defensive_half: bool
    cooldown_days_remaining: int


@dataclass(frozen=True)
class CorePortfolioDecision:
    mode: str
    total_target: Decimal
    total_value: Decimal
    target_gap: Decimal
    full_threshold: Decimal
    ratio_z: Decimal
    route_confirmation_days: int
    rotation_confirmation_days: int
    selected_symbol: str | None
    daily_limit_open: bool
    recommendation: CoreAssetDecision | None
    rotation: CoreRotationDecision
    assets: tuple[CoreAssetDecision, ...]


def evaluate_core_buy(inputs: CoreBuyInputs) -> CoreBuyDecision:
    if inputs.target_gap <= ZERO:
        return _empty("at_target")

    signal_score = _opportunity_score(inputs)
    code = _opportunity_tier(inputs, signal_score)
    if code is None:
        if inputs.last_purchase_date is None or _business_days_between(
            inputs.last_purchase_date, inputs.as_of
        ) >= 20:
            code = "monthly"
        else:
            return _empty("waiting")

    if (
        code != "monthly"
        and inputs.last_purchase_date is not None
        and _business_days_between(inputs.last_purchase_date, inputs.as_of) < 5
        and TIER_RANK[code] <= TIER_RANK.get(inputs.last_purchase_tier or "", 0)
    ):
        return _empty("cooldown")

    fraction = (
        _monthly_fraction(inputs.rsi14)
        if code == "monthly"
        else TIER_FRACTIONS[code]
    )
    trend_reduced = inputs.below_ma200_two_days
    if trend_reduced:
        fraction /= Decimal("2")
    strategy_amount = (inputs.target_gap * fraction).quantize(CENT)
    executable_amount = min(strategy_amount, max(inputs.available_funding, ZERO)).quantize(
        CENT
    )
    funding_required = (strategy_amount - executable_amount).quantize(CENT)
    shares = (
        (executable_amount / inputs.price).quantize(SHARE)
        if inputs.price > ZERO and executable_amount > ZERO
        else ZERO
    )
    return CoreBuyDecision(
        code=code,
        actionable=executable_amount > ZERO,
        fraction=fraction,
        strategy_amount=strategy_amount,
        executable_amount=executable_amount,
        funding_required=funding_required,
        shares=shares,
        signal_score=signal_score,
        trend_reduced=trend_reduced,
    )


def evaluate_core_portfolio(
    assets: list[CoreAssetInputs],
    *,
    as_of: date,
    total_target: Decimal,
    total_equity: Decimal,
    available_funding: Decimal,
    vix: Decimal,
    ratio_z: Decimal,
    route_confirmation_days: int,
    rotation_confirmation_days: int,
    last_account_purchase_date: date | None,
    last_rotation_date: date | None,
    ratio_reset_since_rotation: bool,
) -> CorePortfolioDecision:
    total_value = sum((asset.current_value for asset in assets), ZERO)
    target_gap = max(total_target - total_value, ZERO)
    full_threshold = (total_target * Decimal("0.98")).quantize(CENT)
    mode = "full" if total_target > ZERO and total_value >= full_threshold else "accumulating"
    decisions = tuple(
        _evaluate_asset(
            asset,
            as_of=as_of,
            target_gap=target_gap,
            available_funding=available_funding,
            vix=vix,
        )
        for asset in assets
    )
    daily_limit_open = last_account_purchase_date != as_of
    selected = None
    if mode == "accumulating":
        selected = _select_accumulation_asset(
            decisions,
            ratio_z=ratio_z,
            route_confirmation_days=route_confirmation_days,
        )
        if selected is not None and not daily_limit_open:
            selected = _suppress_asset(selected, "cooldown")
    rotation = _evaluate_rotation(
        decisions,
        as_of=as_of,
        mode=mode,
        total_equity=total_equity,
        ratio_z=ratio_z,
        confirmation_days=rotation_confirmation_days,
        last_rotation_date=last_rotation_date,
        ratio_reset_since_rotation=ratio_reset_since_rotation,
        daily_limit_open=daily_limit_open,
    )
    return CorePortfolioDecision(
        mode=mode,
        total_target=total_target,
        total_value=total_value,
        target_gap=target_gap,
        full_threshold=full_threshold,
        ratio_z=ratio_z,
        route_confirmation_days=route_confirmation_days,
        rotation_confirmation_days=rotation_confirmation_days,
        selected_symbol=selected.symbol if selected is not None else None,
        daily_limit_open=daily_limit_open,
        recommendation=selected,
        rotation=rotation,
        assets=decisions,
    )


def _evaluate_asset(
    asset: CoreAssetInputs,
    *,
    as_of: date,
    target_gap: Decimal,
    available_funding: Decimal,
    vix: Decimal,
) -> CoreAssetDecision:
    decision = evaluate_core_buy(
        CoreBuyInputs(
            as_of=as_of,
            price=asset.price,
            drawdown=asset.drawdown,
            daily_change=asset.daily_change,
            rsi14=asset.rsi14,
            vix=vix,
            target_gap=target_gap,
            available_funding=available_funding,
            last_purchase_date=asset.last_purchase_date,
            last_purchase_tier=asset.last_purchase_tier,
            below_ma200_two_days=asset.below_ma200_two_days,
        )
    )
    return CoreAssetDecision(
        symbol=asset.symbol,
        current_value=asset.current_value,
        price=asset.price,
        drawdown=asset.drawdown,
        daily_change=asset.daily_change,
        rsi14=asset.rsi14,
        ma200=asset.ma200,
        below_ma200_two_days=asset.below_ma200_two_days,
        return_20d=asset.return_20d,
        return_126d=asset.return_126d,
        code=decision.code,
        actionable=decision.actionable,
        fraction=decision.fraction,
        strategy_amount=decision.strategy_amount,
        executable_amount=decision.executable_amount,
        funding_required=decision.funding_required,
        shares=decision.shares,
        signal_score=decision.signal_score,
        trend_reduced=decision.trend_reduced,
    )


def _select_accumulation_asset(
    assets: tuple[CoreAssetDecision, ...],
    *,
    ratio_z: Decimal,
    route_confirmation_days: int,
) -> CoreAssetDecision | None:
    actionable = [asset for asset in assets if asset.actionable]
    if not actionable:
        return max(assets, key=lambda asset: (asset.drawdown, -asset.rsi14), default=None)
    routed_symbol = "VOO" if ratio_z >= Decimal("1") else "BRK.B" if ratio_z <= Decimal("-1") else None
    if routed_symbol and route_confirmation_days >= 3:
        routed = next((asset for asset in actionable if asset.symbol == routed_symbol), None)
        other = next((asset for asset in assets if asset.symbol != routed_symbol), None)
        if routed and other and (
            routed.drawdown >= Decimal("0.03")
            or routed.rsi14 < Decimal("50")
            or other.return_20d - routed.return_20d >= Decimal("0.05")
        ):
            return routed
    return max(
        actionable,
        key=lambda asset: (
            TIER_RANK.get(asset.code, 0),
            asset.drawdown,
            -asset.rsi14,
            asset.symbol == "VOO",
        ),
    )


def _evaluate_rotation(
    assets: tuple[CoreAssetDecision, ...],
    *,
    as_of: date,
    mode: str,
    total_equity: Decimal,
    ratio_z: Decimal,
    confirmation_days: int,
    last_rotation_date: date | None,
    ratio_reset_since_rotation: bool,
    daily_limit_open: bool,
) -> CoreRotationDecision:
    empty = CoreRotationDecision("waiting", False, None, None, ZERO, ZERO, ZERO, ZERO, False, 0)
    if mode != "full" or len(assets) < 2:
        return empty
    sell_symbol = "BRK.B" if ratio_z > ZERO else "VOO"
    buy_symbol = "VOO" if sell_symbol == "BRK.B" else "BRK.B"
    sell = next((asset for asset in assets if asset.symbol == sell_symbol), None)
    buy = next((asset for asset in assets if asset.symbol == buy_symbol), None)
    if sell is None or buy is None:
        return empty
    spread = sell.return_126d - buy.return_126d
    absolute_z = abs(ratio_z)
    tier = None
    fraction = ZERO
    cap = ZERO
    if absolute_z >= Decimal("3") and spread >= Decimal("0.35"):
        tier, fraction, cap = "extreme", Decimal("0.20"), Decimal("0.05")
    elif absolute_z >= Decimal("2.5") and spread >= Decimal("0.25"):
        tier, fraction, cap = "strong", Decimal("0.15"), Decimal("0.04")
    elif absolute_z >= Decimal("2") and spread >= Decimal("0.15"):
        tier, fraction, cap = "standard", Decimal("0.10"), Decimal("0.03")
    if tier is None or confirmation_days < 5:
        return replace(empty, code="watch", sell_symbol=sell_symbol, buy_symbol=buy_symbol, return_spread=spread)
    cooldown_remaining = 0
    if last_rotation_date is not None:
        cooldown_remaining = max(20 - _business_days_between(last_rotation_date, as_of), 0)
    if cooldown_remaining > 0 or not ratio_reset_since_rotation or not daily_limit_open:
        code = "cooldown" if cooldown_remaining > 0 or not daily_limit_open else "reset_wait"
        return replace(
            empty,
            code=code,
            sell_symbol=sell_symbol,
            buy_symbol=buy_symbol,
            return_spread=spread,
            cooldown_days_remaining=cooldown_remaining,
        )
    amount = min(sell.current_value * fraction, total_equity * cap).quantize(CENT)
    defensive_half = buy.below_ma200_two_days
    if defensive_half:
        amount = (amount / Decimal("2")).quantize(CENT)
    return CoreRotationDecision(
        code=tier,
        actionable=amount > ZERO,
        sell_symbol=sell_symbol,
        buy_symbol=buy_symbol,
        amount=amount,
        sell_shares=(amount / sell.price).quantize(SHARE) if sell.price > ZERO else ZERO,
        buy_shares=(amount / buy.price).quantize(SHARE) if buy.price > ZERO else ZERO,
        return_spread=spread,
        defensive_half=defensive_half,
        cooldown_days_remaining=0,
    )


def _suppress_asset(asset: CoreAssetDecision, code: str) -> CoreAssetDecision:
    return replace(
        asset,
        code=code,
        actionable=False,
        fraction=ZERO,
        strategy_amount=ZERO,
        executable_amount=ZERO,
        funding_required=ZERO,
        shares=ZERO,
    )


def relative_ratio_zscores(
    brk_closes: list[Decimal],
    voo_closes: list[Decimal],
    lookback: int = 252,
) -> list[Decimal]:
    ratios = [brk / voo for brk, voo in zip(brk_closes, voo_closes, strict=True) if voo > ZERO]
    if len(ratios) < lookback:
        return []
    values = []
    for end in range(lookback, len(ratios) + 1):
        window = ratios[end - lookback:end]
        mean = sum(window, ZERO) / Decimal(lookback)
        variance = sum(((value - mean) ** 2 for value in window), ZERO) / Decimal(lookback)
        deviation = variance.sqrt() if variance > ZERO else ZERO
        values.append((window[-1] - mean) / deviation if deviation > ZERO else ZERO)
    return values


def consecutive_extreme(values: list[Decimal], threshold: Decimal) -> int:
    if not values or abs(values[-1]) < threshold:
        return 0
    positive = values[-1] > ZERO
    count = 0
    for value in reversed(values):
        if abs(value) < threshold or (value > ZERO) != positive:
            break
        count += 1
    return count


def _opportunity_score(inputs: CoreBuyInputs) -> int:
    score = 0
    if inputs.drawdown >= Decimal("0.15"):
        score += 6
    elif inputs.drawdown >= Decimal("0.10"):
        score += 4
    elif inputs.drawdown >= Decimal("0.05"):
        score += 2
    elif inputs.drawdown >= Decimal("0.03"):
        score += 1

    if inputs.rsi14 < Decimal("30"):
        score += 3
    elif inputs.rsi14 < Decimal("40"):
        score += 2
    elif inputs.rsi14 < Decimal("50"):
        score += 1

    if inputs.daily_change <= Decimal("-0.04"):
        score += 3
    elif inputs.daily_change <= Decimal("-0.02"):
        score += 2
    elif inputs.daily_change <= Decimal("-0.01"):
        score += 1

    if inputs.vix >= Decimal("30"):
        score += 1
    return score


def _opportunity_tier(inputs: CoreBuyInputs, score: int) -> str | None:
    if score >= 6:
        return "deep"
    if score >= 4:
        return "correction"
    if score >= 2:
        return "pullback"
    return None


def _monthly_fraction(rsi14: Decimal) -> Decimal:
    for threshold, fraction in MONTHLY_FRACTIONS:
        if rsi14 >= threshold:
            return fraction
    return TIER_FRACTIONS["monthly"]


def _business_days_between(start: date, end: date) -> int:
    cursor = start + timedelta(days=1)
    count = 0
    while cursor <= end:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def _empty(code: str) -> CoreBuyDecision:
    return CoreBuyDecision(code, False, ZERO, ZERO, ZERO, ZERO, ZERO, 0, False)
