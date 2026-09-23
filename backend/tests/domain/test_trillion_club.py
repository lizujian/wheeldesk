from datetime import date
from decimal import Decimal

from app.domain.trillion_club import (
    ClubMarketState,
    ClubPositionState,
    evaluate_club_entries,
    is_club_symbol,
)


def market(**overrides) -> ClubMarketState:
    values = {
        "symbol": "AAPL",
        "close": Decimal("310"),
        "previous_close": Decimal("325"),
        "ma200": Decimal("280"),
        "rsi14": Decimal("42"),
        "current_price": Decimal("307"),
        "change_fraction": Decimal("-0.055"),
        "live_quote": True,
        "market_cap": Decimal("4200000000000"),
        "market_cap_as_of": date(2026, 6, 30),
        "market_cap_currency": "USD",
        "market_cap_live": True,
        "completed_sessions": 300,
    }
    values.update(overrides)
    return ClubMarketState(**values)


def position(**overrides) -> ClubPositionState:
    values = {
        "position_id": 10,
        "symbol": "AAPL",
        "slot": 1,
        "opened_on": date(2026, 6, 1),
        "underlying_entry_price": Decimal("330"),
    }
    values.update(overrides)
    return ClubPositionState(**values)


def evaluate(markets=None, positions=None, current=Decimal("0"), entries=None):
    return evaluate_club_entries(
        markets or [market()],
        positions or [],
        current,
        Decimal("25000"),
        qqq_above_ma200=True,
        as_of=date(2026, 7, 22),
        confirmed_entry_dates=entries or [],
    )


def test_first_club_entry_uses_the_first_symbol_slot_and_ten_percent_of_the_individual_pool() -> None:
    decision = evaluate()[0]

    assert decision.technical_eligible is True
    assert decision.eligible is True
    assert decision.suggested_slot == 1
    assert decision.suggested_amount == Decimal("2500.00")
    assert decision.open_slots == ()


def test_entire_club_has_one_confirmed_entry_per_market_week() -> None:
    decision = evaluate(entries=[date(2026, 7, 20)])[0]

    assert decision.technical_eligible is False
    assert decision.checks["weekly_limit"] is False
    assert decision.eligible is False


def test_second_symbol_slot_requires_rsi_below_40() -> None:
    blocked = evaluate(positions=[position()], markets=[market(current_price=Decimal("310"))])[0]
    deep_rsi = evaluate(positions=[position()], markets=[market(rsi14=Decimal("39"))])[0]
    deep_price = evaluate(positions=[position()], markets=[market(current_price=Decimal("303"))])[0]

    assert blocked.checks["second_entry"] is False
    assert blocked.technical_eligible is False
    assert deep_rsi.technical_eligible is True
    assert deep_rsi.suggested_slot == 2
    assert deep_price.technical_eligible is False


def test_two_open_positions_keep_the_signal_but_select_same_symbol_fifo() -> None:
    positions = [
        position(position_id=12, slot=2, opened_on=date(2026, 6, 10)),
        position(position_id=8, slot=1, opened_on=date(2026, 5, 10)),
    ]
    decision = evaluate(positions=positions, markets=[market(rsi14=Decimal("39"))])[0]

    assert decision.technical_eligible is True
    assert decision.eligible is False
    assert decision.suggested_slot is None
    assert decision.fifo_candidate_position_id == 8
    assert decision.fifo_candidate_slot == 1


def test_shared_budget_cap_warns_without_hiding_the_technical_signal() -> None:
    decision = evaluate(current=Decimal("25000"))[0]

    assert decision.technical_eligible is True
    assert decision.eligible is False
    assert decision.over_shared_budget is True
    assert decision.suggested_amount == Decimal("0")


def test_market_cap_history_and_trend_checks_are_required() -> None:
    cases = [
        (market(market_cap=Decimal("999999999999")), "market_cap"),
        (market(market_cap_currency="TWD"), "market_cap"),
        (market(completed_sessions=251), "history"),
        (market(close=Decimal("275")), "stock_above_ma200"),
        (market(rsi14=Decimal("45")), "rsi_below_45"),
        (market(change_fraction=Decimal("-0.05")), "daily_drop"),
    ]

    for state, check in cases:
        decision = evaluate(markets=[state])[0]
        assert decision.checks[check] is False
        assert decision.technical_eligible is False


def test_curated_universe_excludes_walmart_and_oracle() -> None:
    assert is_club_symbol("GOOG") is True
    assert is_club_symbol("BRK-B") is True
    assert is_club_symbol("WMT") is False
    assert is_club_symbol("ORCL") is False
