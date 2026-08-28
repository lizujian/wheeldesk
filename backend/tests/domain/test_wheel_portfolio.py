from datetime import date
from decimal import Decimal

import pytest

from app.domain.wheel_portfolio import (
    annualized_return,
    budget_status,
    calculate_exposure,
    early_close_signal,
    recommend_batches,
)


def test_annualized_return_uses_simple_calendar_day_rate() -> None:
    result = annualized_return(
        profit=Decimal("1800"),
        collateral=Decimal("60000"),
        days=45,
    )

    assert result == Decimal("0.243333")
    assert annualized_return(Decimal("100"), Decimal("0"), 10) is None
    assert annualized_return(Decimal("100"), Decimal("1000"), 0) is None


def test_budget_recommendations_use_wheel_bucket_and_sixty_forty_split() -> None:
    result = recommend_batches(Decimal("100000"), Decimal("0"))

    assert result.first == Decimal("60000.00")
    assert result.second == Decimal("40000.00")


def test_recommendation_is_limited_by_remaining_budget() -> None:
    result = recommend_batches(Decimal("100000"), Decimal("60000"))

    assert result.first == Decimal("40000.00")
    assert result.second == Decimal("40000.00")


def test_exposure_counts_open_puts_and_remaining_assigned_shares_once() -> None:
    exposure = calculate_exposure(
        put_collateral=[Decimal("40000")],
        assigned_share_capital=[Decimal("55000")],
    )

    assert exposure == Decimal("95000.00")


def test_over_budget_is_reported_but_does_not_invalidate_a_trade() -> None:
    result = budget_status(Decimal("100000"), Decimal("113000"))

    assert result.over_budget == Decimal("13000.00")
    assert result.available == Decimal("0.00")
    assert result.usage_fraction == Decimal("1.13")


def test_zero_budget_reports_full_exposure_without_a_usage_ratio() -> None:
    result = budget_status(Decimal("0"), Decimal("60000"))

    assert result.over_budget == Decimal("60000.00")
    assert result.available == Decimal("0.00")
    assert result.usage_fraction is None


@pytest.mark.parametrize("budget, exposure", [("-1", "0"), ("0", "-1")])
def test_budget_values_cannot_be_negative(budget: str, exposure: str) -> None:
    with pytest.raises(ValueError, match="不能为负数"):
        budget_status(Decimal(budget), Decimal(exposure))


def test_fast_profit_capture_signal_uses_ten_days_and_fifty_percent() -> None:
    signal = early_close_signal(
        opened_on=date(2026, 7, 1),
        expiration=date(2026, 8, 15),
        as_of=date(2026, 7, 8),
        opening_premium=Decimal("2.00"),
        reference_buyback=Decimal("0.90"),
        quote_source="public",
    )

    assert signal.code == "fast_profit"
    assert signal.captured_fraction == Decimal("0.55")
    assert signal.actionable is True
    assert "建议提前平仓" in signal.message


def test_regular_profit_has_priority_at_seventy_five_percent() -> None:
    signal = early_close_signal(
        opened_on=date(2026, 7, 1),
        expiration=date(2026, 8, 15),
        as_of=date(2026, 7, 8),
        opening_premium=Decimal("2.00"),
        reference_buyback=Decimal("0.50"),
        quote_source="public",
    )

    assert signal.code == "regular_profit"


def test_expiry_profit_uses_twenty_one_dte_and_fifty_percent() -> None:
    signal = early_close_signal(
        opened_on=date(2026, 6, 1),
        expiration=date(2026, 7, 30),
        as_of=date(2026, 7, 10),
        opening_premium=Decimal("2.00"),
        reference_buyback=Decimal("1.00"),
        quote_source="public",
    )

    assert signal.code == "expiry_profit"


def test_theoretical_profit_zone_requires_broker_confirmation() -> None:
    signal = early_close_signal(
        opened_on=date(2026, 7, 1),
        expiration=date(2026, 8, 15),
        as_of=date(2026, 7, 8),
        opening_premium=Decimal("2.00"),
        reference_buyback=Decimal("0.90"),
        quote_source="theoretical",
    )

    assert signal.code == "fast_profit"
    assert signal.actionable is False
    assert "券商确认" in signal.message


def test_no_signal_below_profit_thresholds() -> None:
    signal = early_close_signal(
        opened_on=date(2026, 7, 1),
        expiration=date(2026, 8, 30),
        as_of=date(2026, 7, 20),
        opening_premium=Decimal("2.00"),
        reference_buyback=Decimal("1.20"),
        quote_source="public",
    )

    assert signal.code is None
    assert signal.captured_fraction == Decimal("0.40")
    assert signal.actionable is False
