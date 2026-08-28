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
        "rsi14": Decimal("55"),
        "vix": Decimal("18"),
        "target_gap": Decimal("50000"),
        "available_funding": Decimal("40000"),
        "last_purchase_date": None,
        "last_purchase_tier": None,
    }
    values.update(overrides)
    return CoreBuyInputs(**values)


def test_core_uses_monthly_dca_for_the_first_or_overdue_purchase() -> None:
    decision = evaluate_core_buy(inputs())

    assert decision.code == "monthly"
    assert decision.fraction == Decimal("0.10")
    assert decision.strategy_amount == Decimal("5000.00")
    assert decision.executable_amount == Decimal("5000.00")
    assert decision.shares == Decimal("10.0000")


def test_core_selects_only_the_highest_active_pullback_tier() -> None:
    pullback = evaluate_core_buy(
        inputs(drawdown=Decimal("0.06"), rsi14=Decimal("48"))
    )
    correction = evaluate_core_buy(
        inputs(drawdown=Decimal("0.10"), rsi14=Decimal("48"))
    )
    deep = evaluate_core_buy(inputs(vix=Decimal("31")))

    assert (pullback.code, pullback.fraction) == ("pullback", Decimal("0.20"))
    assert (correction.code, correction.fraction) == (
        "correction",
        Decimal("0.30"),
    )
    assert (deep.code, deep.fraction) == ("deep", Decimal("0.40"))


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
    assert decision.recommendation.strategy_amount == Decimal("5500.00")
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
            asset("BRK.B", current_value=Decimal("60000"), price=Decimal("500"), return_126d=Decimal("0.30")),
            asset("VOO", current_value=Decimal("40000"), price=Decimal("400"), return_126d=Decimal("0.10")),
        ],
        ratio_z=Decimal("2.2"),
        route_confirmation_days=8,
        rotation_confirmation_days=5,
    )

    assert decision.mode == "full"
    assert decision.recommendation is None
    assert decision.rotation.actionable is True
    assert decision.rotation.code == "standard"
    assert decision.rotation.sell_symbol == "BRK.B"
    assert decision.rotation.buy_symbol == "VOO"
    assert decision.rotation.amount == Decimal("6000.00")
    assert decision.rotation.sell_shares == Decimal("12.0000")
    assert decision.rotation.buy_shares == Decimal("15.0000")


def test_full_core_halves_rotation_when_destination_breaks_ma200() -> None:
    decision = portfolio(
        [
            asset("BRK.B", current_value=Decimal("60000"), return_126d=Decimal("0.30")),
            asset("VOO", current_value=Decimal("40000"), return_126d=Decimal("0.10"), below_ma200_two_days=True),
        ],
        ratio_z=Decimal("2.2"),
        rotation_confirmation_days=5,
    )

    assert decision.rotation.actionable is True
    assert decision.rotation.defensive_half is True
    assert decision.rotation.amount == Decimal("3000.00")


def test_full_core_rotation_respects_twenty_day_cooldown() -> None:
    decision = portfolio(
        [
            asset("BRK.B", current_value=Decimal("60000"), return_126d=Decimal("0.30")),
            asset("VOO", current_value=Decimal("40000"), return_126d=Decimal("0.10")),
        ],
        ratio_z=Decimal("2.2"),
        rotation_confirmation_days=5,
        last_rotation_date=date(2026, 7, 15),
    )

    assert decision.rotation.actionable is False
    assert decision.rotation.code == "cooldown"
    assert decision.rotation.cooldown_days_remaining > 0
