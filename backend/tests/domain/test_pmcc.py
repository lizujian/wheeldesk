from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.domain.pmcc import build_pmcc_states, pmcc_budget, summarize_pmcc


def long_call(**overrides):
    values = {
        "id": 1,
        "bucket": "leaps",
        "status": "open",
        "direction": "long",
        "asset_type": "option",
        "option_type": "call",
        "symbol": "QQQ",
        "quantity": Decimal("2"),
        "multiplier": 100,
        "entry_price": Decimal("100"),
        "current_price": Decimal("120"),
        "expiration": date(2027, 1, 15),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def short_call(**overrides):
    values = {
        "id": 10,
        "category": "leaps_call_wheel",
        "status": "open",
        "direction": "short",
        "asset_type": "option",
        "option_type": "call",
        "symbol": "QQQ",
        "quantity": Decimal("1"),
        "multiplier": 100,
        "entry_price": Decimal("5"),
        "current_price": Decimal("2"),
        "expiration": date(2026, 10, 2),
        "strike": Decimal("500"),
        "linked_position_id": 1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_pmcc_budget_splits_the_twenty_five_percent_pool() -> None:
    budget = pmcc_budget(Decimal("100000"))

    assert budget.total_target == Decimal("25000.00")
    assert budget.qqq_target == Decimal("10000.00")
    assert budget.individual_target == Decimal("15000.00")
    assert budget.individual_symbol_cap == Decimal("3000.00")
    assert budget.qqq_slot_target == Decimal("2000.00")
    assert budget.individual_slot_target == Decimal("1500.00")


def test_pmcc_tracks_coverage_net_cash_flow_and_assignment_risk() -> None:
    states = build_pmcc_states(
        [long_call()],
        [short_call()],
        as_of=date(2026, 9, 23),
        underlying_prices={"QQQ": Decimal("510")},
    )

    state = states[0]
    assert state.status == "assignment_risk"
    assert state.covered_contracts == Decimal("2")
    assert state.coverage_ratio == Decimal("0.5000")
    assert state.long_debit == Decimal("20000.00")
    assert state.short_premium_received == Decimal("500.00")
    assert state.short_buyback_cost == Decimal("200.00")
    assert state.net_cash_flow == Decimal("300.00")
    assert state.maximum_loss == Decimal("20000.00")
    assert state.needs_roll is True


def test_unlinked_short_call_is_never_counted_as_covered_pmcc() -> None:
    states = build_pmcc_states(
        [],
        [short_call(linked_position_id=None)],
        as_of=date(2026, 9, 23),
        underlying_prices={"QQQ": Decimal("450")},
    )

    assert len(states) == 1
    assert states[0].status == "uncovered"
    assert states[0].long_position_id is None
    assert states[0].maximum_loss == Decimal("0.00")


def test_pmcc_summary_exposes_the_qqq_budget_overage() -> None:
    states = build_pmcc_states(
        [long_call()],
        [short_call()],
        as_of=date(2026, 9, 23),
    )
    summary = summarize_pmcc(states, Decimal("100000"))

    assert summary["qqq"]["committed"] == Decimal("20000.00")
    assert summary["qqq"]["target"] == Decimal("10000.00")
    assert summary["qqq"]["over"] == Decimal("10000.00")
    assert summary["total"]["net_cash_flow"] == Decimal("300.00")
