from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Sequence

from app.domain.indicators import SupportLevel


@dataclass(frozen=True)
class SellPutDecision:
    eligible: bool
    checks: dict[str, bool]
    dte_min: int
    dte_max: int
    delta_min: Decimal
    delta_max: Decimal
    otm_pct: Decimal
    preferred_support: SupportLevel | None
    reference_strike: Decimal


@dataclass(frozen=True)
class RiskDecision:
    severity: str
    stop_required: bool
    defensive_cc_required_if_holding: bool
    message: str


def evaluate_sell_put(
    qqq_close: Decimal,
    qqq_ma200: Decimal,
    qqq_rsi14: Decimal,
    qqq_bearish: bool,
    tqqq_spot: Decimal,
    supports: Sequence[SupportLevel],
) -> SellPutDecision:
    if tqqq_spot <= 0:
        raise ValueError("TQQQ 现价必须大于零")
    checks = {
        "above_ma200": qqq_close > qqq_ma200,
        "rsi_below_50": qqq_rsi14 < Decimal("50"),
        "bearish_candle": qqq_bearish,
    }
    confirmed = [level for level in supports if level.touches >= 2]
    preferred = (confirmed or list(supports) or [None])[0]
    ten_percent_otm = tqqq_spot * Decimal("0.90")
    conservative_level = min(ten_percent_otm, preferred.price) if preferred else ten_percent_otm
    reference_strike = conservative_level.quantize(Decimal("1"), rounding=ROUND_FLOOR)
    return SellPutDecision(
        eligible=all(checks.values()),
        checks=checks,
        dte_min=30,
        dte_max=45,
        delta_min=Decimal("0.20"),
        delta_max=Decimal("0.30"),
        otm_pct=Decimal("0.10"),
        preferred_support=preferred,
        reference_strike=reference_strike,
    )


def evaluate_risk(effective_ma200_break: bool, has_tqqq_exposure: bool) -> RiskDecision:
    if effective_ma200_break and has_tqqq_exposure:
        return RiskDecision(
            severity="critical",
            stop_required=True,
            defensive_cc_required_if_holding=True,
            message="QQQ 连续两日收于 MA200 下方，立即评估平仓止损；继续持股时只能使用近价或价内 Covered Call 防御。",
        )
    return RiskDecision(
        severity="info",
        stop_required=False,
        defensive_cc_required_if_holding=False,
        message="未触发 QQQ MA200 高危规则。",
    )

