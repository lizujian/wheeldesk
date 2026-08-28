from decimal import Decimal

from app.domain.indicators import SupportLevel
from app.domain.wheel import evaluate_risk, evaluate_sell_put


def support(price: str, touches: int = 2) -> SupportLevel:
    value = Decimal(price)
    return SupportLevel(
        price=value,
        kind="swing_cluster",
        touches=touches,
        distance_pct=(Decimal("100") - value) / Decimal("100"),
    )


def test_sell_put_requires_all_three_qqq_conditions() -> None:
    decision = evaluate_sell_put(
        qqq_close=Decimal("510"),
        qqq_ma200=Decimal("500"),
        qqq_rsi14=Decimal("44"),
        qqq_bearish=True,
        tqqq_spot=Decimal("100"),
        supports=[support("89")],
    )

    assert decision.eligible is True
    assert all(decision.checks.values())
    assert (decision.dte_min, decision.dte_max) == (30, 45)


def test_sell_put_is_not_eligible_when_one_condition_fails() -> None:
    decision = evaluate_sell_put(
        qqq_close=Decimal("510"),
        qqq_ma200=Decimal("500"),
        qqq_rsi14=Decimal("51"),
        qqq_bearish=True,
        tqqq_spot=Decimal("100"),
        supports=[],
    )

    assert decision.eligible is False
    assert decision.checks["rsi_below_50"] is False


def test_strike_reference_uses_more_conservative_of_support_and_10_percent_otm() -> None:
    decision = evaluate_sell_put(
        qqq_close=Decimal("510"),
        qqq_ma200=Decimal("500"),
        qqq_rsi14=Decimal("44"),
        qqq_bearish=True,
        tqqq_spot=Decimal("100"),
        supports=[support("92"), support("87", touches=1)],
    )

    assert decision.preferred_support.price == Decimal("92")
    assert decision.reference_strike == Decimal("90")
    assert decision.otm_pct == Decimal("0.10")


def test_strike_reference_moves_below_deeper_confirmed_support() -> None:
    decision = evaluate_sell_put(
        qqq_close=Decimal("510"),
        qqq_ma200=Decimal("500"),
        qqq_rsi14=Decimal("44"),
        qqq_bearish=True,
        tqqq_spot=Decimal("100"),
        supports=[support("87")],
    )

    assert decision.reference_strike == Decimal("87")


def test_effective_ma200_break_is_critical_only_with_tqqq_exposure() -> None:
    exposed = evaluate_risk(effective_ma200_break=True, has_tqqq_exposure=True)
    unexposed = evaluate_risk(effective_ma200_break=True, has_tqqq_exposure=False)

    assert exposed.severity == "critical"
    assert exposed.stop_required is True
    assert exposed.defensive_cc_required_if_holding is True
    assert unexposed.severity == "info"

