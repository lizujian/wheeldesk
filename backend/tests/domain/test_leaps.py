from datetime import date
from decimal import Decimal

import pytest

from app.domain.leaps import (
    LeapsExitInputs,
    LeapsMarketState,
    evaluate_leaps_equity_exit,
    evaluate_leaps_exit,
    evaluate_leaps_tranches,
    roll_priority,
    select_fifo_position,
    validate_leaps_contract,
)


def state(**overrides) -> LeapsMarketState:
    values = {
        "close": Decimal("460"),
        "previous_close": Decimal("455"),
        "ma20": Decimal("458"),
        "previous_ma20": Decimal("457"),
        "ma200": Decimal("440"),
        "drawdown": Decimal("0.10"),
        "rsi14": Decimal("42"),
        "previous_rsi14": Decimal("40"),
        "previous_above_ma20": False,
        "two_closes_above_ma20": False,
        "current_price": Decimal("455"),
        "session_quote_live": True,
    }
    values.update(overrides)
    return LeapsMarketState(**values)


def test_three_entry_checks_open_only_the_next_empty_slot_at_five_percent() -> None:
    decisions = evaluate_leaps_tranches(
        state(),
        {1},
        Decimal("5000"),
        Decimal("25000"),
        as_of=date(2026, 7, 22),
        last_entry_date=date(2026, 7, 21),
    )

    assert len(decisions) == 5
    assert decisions[0].eligible is False
    assert decisions[1].eligible is True
    assert decisions[1].allocation_fraction == Decimal("0.20")
    assert decisions[1].suggested_amount == Decimal("5000.00")
    assert decisions[1].checks == {
        "above_ma200": True,
        "rsi_below_45": True,
        "daily_drop": True,
        "live_quote": True,
        "daily_limit": True,
        "next_slot": True,
    }
    assert decisions[2].eligible is False


@pytest.mark.parametrize(
    ("overrides", "failed_check"),
    [
        ({"close": Decimal("440")}, "above_ma200"),
        ({"rsi14": Decimal("45")}, "rsi_below_45"),
        ({"current_price": Decimal("455.5")}, "daily_drop"),
        ({"session_quote_live": False}, "live_quote"),
    ],
)
def test_each_leaps_entry_condition_is_required(overrides, failed_check) -> None:
    decisions = evaluate_leaps_tranches(
        state(**overrides),
        set(),
        Decimal("0"),
        Decimal("25000"),
        as_of=date(2026, 7, 24),
        last_entry_date=None,
    )

    assert all(decision.eligible is False for decision in decisions)
    assert decisions[0].checks[failed_check] is False


def test_leaps_daily_rate_limit_uses_confirmed_entry_date() -> None:
    decisions = evaluate_leaps_tranches(
        state(),
        set(),
        Decimal("0"),
        Decimal("25000"),
        as_of=date(2026, 7, 24),
        last_entry_date=date(2026, 7, 24),
    )

    assert all(decision.eligible is False for decision in decisions)
    assert decisions[0].checks["daily_limit"] is False


def test_session_change_keeps_the_regular_day_drop_after_market_close() -> None:
    decisions = evaluate_leaps_tranches(
        state(
            close=Decimal("450"),
            current_price=Decimal("451"),
            current_change_fraction=Decimal("-0.021"),
        ),
        set(),
        Decimal("0"),
        Decimal("25000"),
        as_of=date(2026, 7, 24),
        last_entry_date=None,
    )

    assert decisions[0].checks["daily_drop"] is True
    assert decisions[0].eligible is True


def test_no_leaps_slot_is_suggested_at_bucket_cap() -> None:
    decisions = evaluate_leaps_tranches(
        state(),
        set(),
        Decimal("25000"),
        Decimal("25000"),
        as_of=date(2026, 7, 22),
        last_entry_date=None,
    )

    assert all(decision.eligible is False for decision in decisions)
    assert all(decision.suggested_amount == Decimal("0") for decision in decisions)


def test_fifo_selects_oldest_open_position_then_lowest_record_id() -> None:
    candidate = select_fifo_position(
        [
            (9, 3, date(2026, 7, 10)),
            (4, 2, date(2026, 7, 10)),
            (7, 1, date(2026, 7, 11)),
        ]
    )

    assert candidate == {"position_id": 4, "slot": 2, "opened_on": date(2026, 7, 10)}


def test_leaps_contract_requires_a_future_long_call_but_dte_is_advisory() -> None:
    with pytest.raises(ValueError, match="禁止使用 TQQQ"):
        validate_leaps_contract("TQQQ", "call", "long", 365)

    validate_leaps_contract("QQQ", "call", "long", 180)
    validate_leaps_contract("QQQ", "call", "long", 730)
    with pytest.raises(ValueError, match="必须晚于开仓日期"):
        validate_leaps_contract("QQQ", "call", "long", 0)


def exit_inputs(**overrides) -> LeapsExitInputs:
    values = {
        "opened_on": date(2026, 1, 1),
        "expiration": date(2027, 1, 1),
        "as_of": date(2026, 5, 1),
        "entry_price": Decimal("100"),
        "current_bid": Decimal("150"),
    }
    values.update(overrides)
    return LeapsExitInputs(**values)


def test_leaps_exit_uses_dynamic_profit_ladder_boundaries() -> None:
    first = evaluate_leaps_exit(exit_inputs())
    second = evaluate_leaps_exit(
        exit_inputs(
            as_of=date(2026, 5, 2),
            current_bid=Decimal("130"),
        )
    )
    third = evaluate_leaps_exit(
        exit_inputs(
            as_of=date(2026, 7, 1),
            current_bid=Decimal("110"),
        )
    )

    assert (first.days_held, first.code, first.target_return) == (120, "take_profit", Decimal("0.50"))
    assert (second.days_held, second.code, second.target_return) == (121, "take_profit", Decimal("0.30"))
    assert (third.days_held, third.code, third.target_return) == (181, "take_profit", Decimal("0.10"))


def test_leaps_exit_forces_sale_after_270_days_regardless_of_return() -> None:
    decision = evaluate_leaps_exit(
        exit_inputs(
            as_of=date(2026, 9, 29),
            current_bid=Decimal("50"),
        )
    )

    assert decision.days_held == 271
    assert decision.code == "force_exit"
    assert decision.actionable is True


def test_qld_equity_uses_the_same_held_day_profit_ladder_without_a_dte_exit() -> None:
    opened = date(2026, 1, 1)
    first = evaluate_leaps_equity_exit(opened_on=opened, as_of=date(2026, 5, 1), entry_price=Decimal("100"), current_price=Decimal("125"))
    second = evaluate_leaps_equity_exit(opened_on=opened, as_of=date(2026, 5, 2), entry_price=Decimal("100"), current_price=Decimal("115"))
    third = evaluate_leaps_equity_exit(opened_on=opened, as_of=date(2026, 7, 1), entry_price=Decimal("100"), current_price=Decimal("105"))
    late = evaluate_leaps_equity_exit(opened_on=opened, as_of=date(2026, 9, 29), entry_price=Decimal("100"), current_price=Decimal("105"))

    assert (first.days_held, first.code, first.target_return) == (120, "take_profit", Decimal("0.25"))
    assert (second.days_held, second.code, second.target_return) == (121, "take_profit", Decimal("0.15"))
    assert (third.days_held, third.code, third.target_return) == (181, "take_profit", Decimal("0.05"))
    assert (late.days_held, late.code, late.target_return, late.dte) == (271, "take_profit", Decimal("0.05"), None)


def test_leaps_missing_quote_keeps_time_rule_but_suppresses_return_signal() -> None:
    waiting = evaluate_leaps_exit(exit_inputs(current_bid=None))
    forced = evaluate_leaps_exit(
        exit_inputs(as_of=date(2026, 9, 29), current_bid=None)
    )

    assert waiting.code == "quote_unavailable"
    assert waiting.actionable is False
    assert forced.code == "force_exit"


def test_roll_priority_escalates_below_270_dte() -> None:
    assert roll_priority(400) is None
    assert roll_priority(364) == "warning"
    assert roll_priority(269) == "high"
