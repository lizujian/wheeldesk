from datetime import date
from decimal import Decimal

from app.domain.rebalancing import evaluate_core_rebalance, review_schedule


def test_review_is_due_six_calendar_months_after_opening_or_last_confirmation() -> None:
    first = review_schedule(date(2026, 1, 31), None, date(2026, 7, 30))
    due = review_schedule(date(2026, 1, 31), None, date(2026, 7, 31))
    renewed = review_schedule(
        date(2026, 1, 31), date(2026, 6, 15), date(2026, 12, 14)
    )

    assert first.next_review_on == date(2026, 7, 31)
    assert first.due is False
    assert due.due is True
    assert renewed.next_review_on == date(2026, 12, 15)
    assert renewed.due is False


def test_core_rebalance_uses_five_and_ten_point_bands() -> None:
    target = Decimal("0.56")

    assert evaluate_core_rebalance(target, Decimal("0.60"), True, 300000, 500).code == "pause"
    assert evaluate_core_rebalance(target, Decimal("0.63"), True, 300000, 500).code == "observe"
    assert evaluate_core_rebalance(target, Decimal("0.67"), False, 300000, 500).code == "observe"


def test_due_hard_overweight_recommends_selling_to_target_plus_five_points() -> None:
    result = evaluate_core_rebalance(
        target_fraction=Decimal("0.56"),
        actual_fraction=Decimal("0.70"),
        review_due=True,
        total_equity=Decimal("300000"),
        share_price=Decimal("500"),
    )

    assert result.code == "sell"
    assert result.actionable is True
    assert result.target_after_sale == Decimal("0.61")
    assert result.sell_amount == Decimal("27000.00")
    assert result.estimated_shares == Decimal("54.0000")
