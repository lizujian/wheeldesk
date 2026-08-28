from datetime import date
from decimal import Decimal

from app.domain.club_wheel import ClubWheelPositionState, evaluate_club_wheel_entries
from app.domain.indicators import SupportLevel
from app.domain.trillion_club import ClubMarketState


def market(**overrides) -> ClubMarketState:
    values = {
        "symbol": "AAPL",
        "close": Decimal("200"),
        "previous_close": Decimal("205"),
        "ma200": Decimal("180"),
        "rsi14": Decimal("38"),
        "current_price": Decimal("194"),
        "change_fraction": Decimal("-0.0537"),
        "live_quote": True,
        "market_cap": Decimal("3000000000000"),
        "market_cap_as_of": date(2026, 6, 30),
        "market_cap_currency": "USD",
        "market_cap_live": True,
        "completed_sessions": 300,
        "supports": (
            SupportLevel(Decimal("170"), "swing_cluster", 3, Decimal("0.12")),
        ),
        "next_earnings_date": date(2026, 11, 1),
        "earnings_available": True,
    }
    return ClubMarketState(**(values | overrides))


def test_club_wheel_requires_stricter_pullback_and_uses_support_below_ten_percent_otm() -> None:
    decision = evaluate_club_wheel_entries(
        [market()],
        [],
        qqq_above_ma200=True,
        total_equity=Decimal("400000"),
        wheel_budget_available=Decimal("30000"),
        as_of=date(2026, 8, 26),
        confirmed_entry_dates=[],
    )[0]

    assert decision.technical_eligible is True
    assert decision.eligible is True
    assert decision.reference_strike == Decimal("170")
    assert decision.one_contract_collateral == Decimal("17000")
    assert decision.dte_range == (30, 45)
    assert decision.delta_range == (Decimal("0.15"), Decimal("0.25"))
    assert decision.minimum_annualized_return == Decimal("0.12")


def test_club_wheel_keeps_technical_signal_but_flags_budget_and_concentration() -> None:
    decision = evaluate_club_wheel_entries(
        [market()],
        [],
        qqq_above_ma200=True,
        total_equity=Decimal("300000"),
        wheel_budget_available=Decimal("14000"),
        as_of=date(2026, 8, 26),
        confirmed_entry_dates=[],
    )[0]

    assert decision.technical_eligible is True
    assert decision.eligible is False
    assert decision.over_budget is True
    assert decision.over_concentration is True


def test_club_wheel_blocks_same_week_active_cycle_and_near_earnings() -> None:
    positions = [
        ClubWheelPositionState(
            put_id=7,
            symbol="AAPL",
            strike=Decimal("175"),
            state="open",
            captured_fraction=Decimal("-1.1"),
            has_held_shares=False,
        )
    ]
    decision = evaluate_club_wheel_entries(
        [market(next_earnings_date=date(2026, 9, 15), two_closes_below_ma200=True)],
        positions,
        qqq_above_ma200=True,
        total_equity=Decimal("400000"),
        wheel_budget_available=Decimal("30000"),
        as_of=date(2026, 8, 26),
        confirmed_entry_dates=[date(2026, 8, 24)],
    )[0]

    assert decision.technical_eligible is False
    assert decision.checks["weekly_limit"] is False
    assert decision.checks["no_active_cycle"] is False
    assert decision.checks["earnings_clear"] is False
    assert decision.high_risk_put_ids == (7,)


def test_brk_b_is_not_offered_as_a_club_wheel_symbol() -> None:
    decisions = evaluate_club_wheel_entries(
        [market(symbol="BRK-B")],
        [],
        qqq_above_ma200=True,
        total_equity=Decimal("400000"),
        wheel_budget_available=Decimal("30000"),
        as_of=date(2026, 8, 26),
        confirmed_entry_dates=[],
    )

    assert decisions == []
