from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.core_rotation import RotationUsage, evaluate_rotation, ratio_band


def rotate(**overrides):
    inputs = dict(full=True, brk_value=D("100000"), voo_value=D("0"),
                  brk_price=D("400"), voo_price=D("500"),
                  ratios=[(date(2026, 9, day), D("0.8")) for day in (2, 3, 4)])
    inputs.update(overrides)
    return evaluate_rotation(**inputs)


@pytest.mark.parametrize("ratio,target,seller", [
    ("0.88", "0.30", "BRK.B"), ("0.83", "0.55", "BRK.B"), ("0.78", "0.80", "BRK.B"),
    ("0.72", "0.70", "VOO"), ("0.68", "0.85", "VOO"), ("0.65", "1.00", "VOO"),
])
def test_exact_thresholds(ratio, target, seller):
    band = ratio_band(D(ratio))
    assert band[:2] == (seller, D(target))


def test_jump_to_third_band_keeps_twenty_point_execution_cap():
    result = rotate(ratios=[(date(2026, 9, day), D("0.9")) for day in (2, 3, 4)])
    assert result.actionable
    assert result.target_brk_weight == D("0.3")
    assert result.next_brk_weight == D("0.8")
    assert result.amount == D("20000")


def test_more_extreme_closes_confirm_current_band_but_a_single_jump_does_not():
    confirmed = rotate(ratios=[(date(2026, 9, day), value) for day, value in [(2, D(".9")), (3, D(".84")), (4, D(".84"))]])
    assert confirmed.actionable
    unconfirmed = rotate(ratios=[(date(2026, 9, day), value) for day, value in [(2, D(".8")), (3, D(".8")), (4, D(".9"))]])
    assert unconfirmed.code == "confirming"
    assert unconfirmed.confirmation_days == 1


def test_neutral_zone_and_direction_never_force_initial_weights():
    neutral = rotate(brk_value=D("20000"), voo_value=D("80000"), ratios=[(date(2026, 9, day), D(".75")) for day in (2, 3, 4)])
    assert neutral.code == "neutral"
    assert neutral.next_brk_weight == D(".2")
    reverse = rotate(ratios=[(date(2026, 9, day), D(".71")) for day in (2, 3, 4)])
    assert reverse.code == "within_target"
    assert reverse.next_brk_weight == D("1")


def test_partial_executions_consume_shared_window_budget():
    result = rotate(usage=RotationUsage(used_weight=D(".12")))
    assert result.weight_change == D(".08")
    assert result.amount == D("8000")
    assert rotate(usage=RotationUsage(used_weight=D(".20"))).code == "window_limit"
    assert rotate(usage=RotationUsage(complete=False)).code == "execution_unverified"


def test_pending_puts_only_block_the_direction_they_would_reverse():
    blocked = rotate(pending_brk_shares=D("100"))
    assert blocked.code == "pending_puts"
    assert not blocked.actionable
    assert rotate(pending_voo_shares=D("100")).actionable
    projected = rotate(brk_value=D("60000"), voo_value=D("40000"), pending_brk_shares=D("100"))
    assert projected.current_brk_weight == D(".6")
    assert projected.projected_brk_weight == D("100000") / D("140000")


def test_tolerance_missing_data_and_daily_limit():
    assert rotate(brk_value=D("82000"), voo_value=D("18000")).code == "within_target"
    assert not rotate(data_valid=False).actionable
    assert not rotate(ratios=[]).actionable
    assert rotate(daily_limit_open=False).code == "daily_limit"
    assert rotate(brk_price=D("NaN")).code == "invalid_data"
    assert rotate(ratios=[(date(2026, 9, 4), D("0"))]).code == "invalid_data"
