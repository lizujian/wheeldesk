from datetime import date
from decimal import Decimal

from app.domain.core import (
    CoreAssetInputs,
    CoreBuyInputs,
    evaluate_core_buy,
    evaluate_core_portfolio,
)


def inputs(**overrides) -> CoreBuyInputs:
    values = {
        "as_of": date(2026, 7, 22),
        "price": Decimal("500"),
        "drawdown": Decimal("0"),
        "daily_change": Decimal("0"),
        "rsi14": Decimal("55"),
        "vix": Decimal("18"),
        "target_gap": Decimal("50000"),
        "available_funding": Decimal("40000"),
        "last_purchase_date": None,
        "last_purchase_tier": None,
    }
    values.update(overrides)
    return CoreBuyInputs(**values)


def test_core_scales_monthly_dca_down_when_rsi_is_elevated() -> None:
    warm = evaluate_core_buy(inputs(rsi14=Decimal("60")))
    hot = evaluate_core_buy(inputs(rsi14=Decimal("68")))
    normal = evaluate_core_buy(inputs(rsi14=Decimal("48")))

    assert (warm.code, warm.fraction, warm.strategy_amount) == (
        "monthly", Decimal("0.05"), Decimal("2500.00")
    )
    assert (hot.code, hot.fraction, hot.strategy_amount) == (
        "monthly", Decimal("0.025"), Decimal("1250.00")
    )
    assert (normal.code, normal.fraction, normal.strategy_amount) == (
        "monthly", Decimal("0.10"), Decimal("5000.00")
    )


def test_core_selects_only_the_highest_active_pullback_tier() -> None:
    pullback = evaluate_core_buy(
        inputs(drawdown=Decimal("0.06"), rsi14=Decimal("48"))
    )
    correction = evaluate_core_buy(
        inputs(drawdown=Decimal("0.10"), rsi14=Decimal("48"))
    )
    deep = evaluate_core_buy(inputs(drawdown=Decimal("0.16")))

    assert (pullback.code, pullback.fraction) == ("pullback", Decimal("0.20"))
    assert (correction.code, correction.fraction) == (
        "correction",
        Decimal("0.30"),
    )
    assert (deep.code, deep.fraction) == ("deep", Decimal("0.40"))


def test_core_combines_daily_drop_rsi_and_drawdown_into_opportunity_tiers() -> None:
    pullback = evaluate_core_buy(
        inputs(daily_change=Decimal("-0.012"), rsi14=Decimal("48"))
    )
    correction = evaluate_core_buy(
        inputs(
            daily_change=Decimal("-0.021"),
            drawdown=Decimal("0.03"),
            rsi14=Decimal("44"),
        )
    )
    deep = evaluate_core_buy(
        inputs(
            daily_change=Decimal("-0.011"),
            drawdown=Decimal("0.06"),
            rsi14=Decimal("29"),
        )
    )

    assert (pullback.code, pullback.signal_score) == ("pullback", 2)
    assert (correction.code, correction.signal_score) == ("correction", 4)
    assert (deep.code, deep.signal_score) == ("deep", 6)


def test_core_halves_staged_buy_below_ma200_for_two_days() -> None:
    decision = evaluate_core_buy(
        inputs(drawdown=Decimal("0.10"), below_ma200_two_days=True)
    )

    assert decision.code == "correction"
    assert decision.trend_reduced is True
    assert decision.fraction == Decimal("0.15")
    assert decision.strategy_amount == Decimal("7500.00")


def test_core_caps_executable_amount_by_funding_and_reports_shortfall() -> None:
    decision = evaluate_core_buy(
        inputs(
            drawdown=Decimal("0.16"),
            target_gap=Decimal("10000"),
            available_funding=Decimal("1200"),
        )
    )

    assert decision.strategy_amount == Decimal("4000.00")
    assert decision.executable_amount == Decimal("1200.00")
    assert decision.funding_required == Decimal("2800.00")
    assert decision.shares == Decimal("2.4000")


def test_core_suppresses_same_or_lower_tier_during_five_day_cooldown() -> None:
    decision = evaluate_core_buy(
        inputs(
            drawdown=Decimal("0.11"),
            last_purchase_date=date(2026, 7, 20),
            last_purchase_tier="correction",
        )
    )

    assert decision.code == "cooldown"
    assert decision.actionable is False
    assert decision.executable_amount == Decimal("0")


def test_core_allows_a_deeper_tier_to_override_cooldown() -> None:
    decision = evaluate_core_buy(
        inputs(
            drawdown=Decimal("0.16"),
            last_purchase_date=date(2026, 7, 20),
            last_purchase_tier="pullback",
        )
    )

    assert decision.code == "deep"
    assert decision.actionable is True


def test_core_emits_no_purchase_at_or_above_target() -> None:
    decision = evaluate_core_buy(inputs(target_gap=Decimal("0")))

    assert decision.code == "at_target"
    assert decision.actionable is False


def asset(symbol: str, **overrides) -> CoreAssetInputs:
    values = {
        "symbol": symbol,
        "current_value": Decimal("0"),
        "price": Decimal("500"),
        "drawdown": Decimal("0"),
        "daily_change": Decimal("0"),
        "rsi14": Decimal("55"),
        "ma200": Decimal("450"),
        "below_ma200_two_days": False,
        "return_20d": Decimal("0"),
        "return_126d": Decimal("0"),
        "last_purchase_date": None,
        "last_purchase_tier": None,
    }
    values.update(overrides)
    return CoreAssetInputs(**values)


def portfolio(assets: list[CoreAssetInputs], **overrides):
    values = {
        "as_of": date(2026, 7, 22),
        "total_target": Decimal("100000"),
        "total_equity": Decimal("200000"),
        "available_funding": Decimal("50000"),
        "vix": Decimal("18"),
        "ratio_z": Decimal("0"),
        "route_confirmation_days": 0,
        "rotation_confirmation_days": 0,
        "last_account_purchase_date": None,
        "last_rotation_date": None,
        "ratio_reset_since_rotation": True,
    }
    values.update(overrides)
    return evaluate_core_portfolio(assets, **values)


def test_core_portfolio_routes_new_money_to_voo_after_confirmed_relative_gap() -> None:
    decision = evaluate_core_portfolio(
        [
            asset("BRK.B", current_value=Decimal("30000"), return_20d=Decimal("0.08")),
            asset("VOO", current_value=Decimal("15000"), price=Decimal("600"), drawdown=Decimal("0.04")),
        ],
        as_of=date(2026, 7, 22),
        total_target=Decimal("100000"),
        total_equity=Decimal("200000"),
        available_funding=Decimal("50000"),
        vix=Decimal("18"),
        ratio_z=Decimal("1.2"),
        route_confirmation_days=3,
        rotation_confirmation_days=0,
        last_account_purchase_date=None,
        last_rotation_date=None,
        ratio_reset_since_rotation=True,
    )

    assert decision.selected_symbol == "VOO"
    assert decision.recommendation is not None
    assert decision.recommendation.actionable is True
    assert decision.recommendation.strategy_amount == Decimal("2750.00")
    assert decision.mode == "accumulating"


def test_core_portfolio_prefers_the_deeper_pullback_in_neutral_relative_range() -> None:
    decision = portfolio(
        [
            asset("BRK.B", current_value=Decimal("20000"), drawdown=Decimal("0.11")),
            asset("VOO", current_value=Decimal("20000"), drawdown=Decimal("0.04")),
        ],
    )

    assert decision.selected_symbol == "BRK.B"
    assert decision.recommendation is not None
    assert decision.recommendation.code == "correction"


def test_pending_core_puts_pause_routine_buying_for_both_core_symbols() -> None:
    decision = portfolio(
        [asset("BRK.B"), asset("VOO", drawdown=Decimal("0.06"))],
        pending_put_collateral=Decimal("50000"),
    )

    assert decision.target_gap == Decimal("100000")
    assert decision.unplanned_gap == Decimal("50000")
    assert all(item.code == "pending_puts" and not item.actionable for item in decision.assets)
    assert not decision.recommendation.actionable


def test_pending_puts_preserve_deeper_opportunities_using_only_unplanned_gap() -> None:
    decision = portfolio(
        [asset("BRK.B", current_value=Decimal("20000"), drawdown=Decimal("0.10")), asset("VOO")],
        pending_put_collateral=Decimal("50000"),
        available_funding=Decimal("6000"),
    )

    assert decision.target_gap == Decimal("80000")
    assert decision.unplanned_gap == Decimal("30000")
    assert decision.recommendation.code == "correction"
    assert decision.recommendation.strategy_amount == Decimal("9000")
    assert decision.recommendation.executable_amount == Decimal("6000")


def test_fully_planned_core_does_not_buy_more_or_rotate_unassigned_shares() -> None:
    decision = portfolio(
        [asset("BRK.B", drawdown=Decimal("0.16")), asset("VOO")],
        pending_put_collateral=Decimal("100000"),
    )

    assert decision.mode == "accumulating"
    assert decision.total_value == 0
    assert decision.unplanned_gap == 0
    assert not decision.recommendation.actionable
    assert not decision.rotation.actionable


def test_routine_dca_resumes_when_no_core_puts_remain() -> None:
    decision = portfolio([asset("BRK.B"), asset("VOO")], pending_put_collateral=Decimal("0"))
    assert decision.recommendation.actionable
    assert decision.recommendation.code == "monthly"


def test_core_put_routes_mild_pullback_to_one_cash_secured_contract() -> None:
    decision = portfolio(
        [asset("BRK.B", daily_change=Decimal("-0.012"), rsi14=Decimal("48"), support_price=Decimal("480"))],
        available_funding=Decimal("100000"),
    )
    assert decision.sell_put.actionable
    assert decision.sell_put.contracts == 1
    assert decision.sell_put.reference_strike == Decimal("480")
    assert decision.sell_put.collateral == Decimal("48000")
    assert decision.sell_put.direct_buy_reserve == Decimal("50000")
    assert decision.recommendation.code == "put_preferred"
    assert not decision.recommendation.actionable


def test_core_put_preserves_direct_buy_reserve_and_target_capacity() -> None:
    candidate = asset("VOO", daily_change=Decimal("-0.012"), rsi14=Decimal("48"), support_price=Decimal("480"))
    short_cash = portfolio([candidate], available_funding=Decimal("60000"))
    short_gap = portfolio([candidate], available_funding=Decimal("100000"), total_target=Decimal("40000"))
    assert short_cash.sell_put.code == "insufficient_reserve"
    assert short_gap.sell_put.code == "insufficient_reserve"
    assert not short_cash.sell_put.actionable
    assert short_cash.recommendation.actionable


def test_core_put_waits_for_support_trend_and_no_pending_assignments() -> None:
    candidate = asset("BRK.B", daily_change=Decimal("-0.012"), rsi14=Decimal("48"))
    assert portfolio([candidate], available_funding=Decimal("100000")).sell_put.code == "no_support"
    assert portfolio([candidate], pending_put_collateral=Decimal("50000")).sell_put.code == "pending_puts"
    broken = asset("BRK.B", ma200=Decimal("520"), daily_change=Decimal("-0.012"), rsi14=Decimal("48"), support_price=Decimal("480"))
    assert not portfolio([broken], available_funding=Decimal("100000")).sell_put.actionable
    deeper = asset("BRK.B", drawdown=Decimal("0.16"), support_price=Decimal("480"))
    assert portfolio([deeper]).sell_put.code == "direct_buy_preferred"


def test_core_portfolio_blocks_a_second_core_purchase_on_the_same_day() -> None:
    decision = portfolio(
        [asset("BRK.B"), asset("VOO")],
        last_account_purchase_date=date(2026, 7, 22),
    )

    assert decision.daily_limit_open is False
    assert decision.recommendation is not None
    assert decision.recommendation.actionable is False
    assert decision.recommendation.code == "cooldown"


def test_full_core_emits_a_cash_neutral_standard_rotation() -> None:
    decision = portfolio(
        [
            asset("BRK.B", current_value=Decimal("100000"), price=Decimal("400")),
            asset("VOO", current_value=Decimal("0"), price=Decimal("500")),
        ],
        ratio_z=Decimal("2.2"),
        route_confirmation_days=8,
        rotation_confirmation_days=5,
        rotation_ratios=[(date(2026, 7, day), Decimal("0.80")) for day in (20, 21, 22)],
    )

    assert decision.mode == "full"
    assert decision.recommendation is None
    assert decision.rotation.actionable is True
    assert decision.rotation.code == "opportunity"
    assert decision.rotation.sell_symbol == "BRK.B"
    assert decision.rotation.buy_symbol == "VOO"
    assert decision.rotation.amount == Decimal("20000.00")
    assert decision.rotation.sell_shares == Decimal("50.0000")
    assert decision.rotation.buy_shares == Decimal("40.0000")


def test_core_uses_completed_prices_for_fullness_before_rotation() -> None:
    decision = portfolio(
        [
            asset("BRK.B", current_value=Decimal("100000"), price=Decimal("500")),
            asset("VOO", current_value=Decimal("0"), price=Decimal("600")),
        ],
        ratio_z=Decimal("2.2"),
        rotation_confirmation_days=5,
        rotation_prices={"BRK.B": Decimal("450"), "VOO": Decimal("600")},
        rotation_ratios=[(date(2026, 7, day), Decimal("0.80")) for day in (20, 21, 22)],
    )

    assert decision.mode == "full"
    assert decision.rotation.actionable is False
    assert decision.rotation.code == "waiting"


def test_unfilled_core_never_rotates_even_with_extreme_ratio() -> None:
    decision = portfolio(
        [
            asset("BRK.B", current_value=Decimal("40000")),
            asset("VOO", current_value=Decimal("0")),
        ],
        ratio_z=Decimal("2.2"),
        rotation_confirmation_days=5,
        last_rotation_date=date(2026, 7, 15),
        rotation_ratios=[(date(2026, 7, day), Decimal("0.90")) for day in (20, 21, 22)],
    )

    assert decision.rotation.actionable is False
    assert decision.rotation.code == "waiting"
