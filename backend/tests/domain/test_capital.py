from decimal import Decimal

from app.domain.capital import apply_loss, cash_capacity, strategy_capacity


def test_strategy_capacity_separates_assigned_committed_and_cash_occupancy() -> None:
    covered = strategy_capacity(Decimal("81600"), Decimal("154000"))

    assert covered.assigned == Decimal("81600.00")
    assert covered.committed == Decimal("154000.00")
    assert covered.available == Decimal("0.00")
    assert covered.cash_occupancy == Decimal("72400.00")


def test_cash_capacity_reports_available_cash_and_margin_shortfall() -> None:
    status = cash_capacity(
        Decimal("30000"),
        wheel_occupancy=Decimal("72400"),
        leaps_occupancy=Decimal("5000"),
    )

    assert status.total == Decimal("30000.00")
    assert status.occupied == Decimal("77400.00")
    assert status.available == Decimal("0.00")
    assert status.margin_shortfall == Decimal("47400.00")


def test_loss_reduces_strategy_first_and_then_cash_without_negative_balances() -> None:
    within_bucket = apply_loss(Decimal("20400"), Decimal("30000"), Decimal("6000"))
    beyond_bucket = apply_loss(Decimal("4000"), Decimal("30000"), Decimal("6500"))

    assert within_bucket.strategy_after == Decimal("14400.00")
    assert within_bucket.cash_after == Decimal("30000.00")
    assert beyond_bucket.strategy_after == Decimal("0.00")
    assert beyond_bucket.cash_after == Decimal("27500.00")
    assert beyond_bucket.uncovered == Decimal("0.00")


def test_loss_reports_uncovered_amount_when_strategy_and_cash_are_exhausted() -> None:
    result = apply_loss(Decimal("1000"), Decimal("500"), Decimal("2000"))

    assert result.strategy_after == Decimal("0.00")
    assert result.cash_after == Decimal("0.00")
    assert result.uncovered == Decimal("500.00")
