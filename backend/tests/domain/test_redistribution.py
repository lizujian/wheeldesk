from decimal import Decimal

import pytest

from app.domain.models import Bucket
from app.domain.redistribution import recommend_distribution


def test_distribution_refills_cash_then_core_before_option_pools() -> None:
    recommendation = recommend_distribution(
        distributable_profit=Decimal("10000"),
        total_equity=Decimal("100000"),
        age=30,
        current_values={
            Bucket.CASH: Decimal("5000"),
            Bucket.CORE: Decimal("48000"),
            Bucket.WHEEL: Decimal("32000"),
            Bucket.LEAPS: Decimal("5000"),
        },
    )

    assert recommendation.allocations[Bucket.CASH] == Decimal("0.00")
    assert recommendation.allocations[Bucket.CORE] == Decimal("10000.00")
    assert recommendation.allocations[Bucket.LEAPS] == Decimal("0.00")
    assert recommendation.allocations[Bucket.WHEEL] == Decimal("0.00")
    assert recommendation.unallocated == Decimal("0.00")


def test_remaining_profit_goes_to_the_shared_option_pool() -> None:
    recommendation = recommend_distribution(
        distributable_profit=Decimal("8000"),
        total_equity=Decimal("100000"),
        age=30,
        current_values={
            Bucket.CASH: Decimal("10000"),
            Bucket.CORE: Decimal("70000"),
            Bucket.WHEEL: Decimal("2000"),
            Bucket.LEAPS: Decimal("4000"),
        },
    )

    assert recommendation.allocations[Bucket.WHEEL] == Decimal("0.00")
    assert recommendation.allocations[Bucket.LEAPS] == Decimal("8000.00")


def test_leaps_at_cap_receives_no_more_profit() -> None:
    recommendation = recommend_distribution(
        distributable_profit=Decimal("4000"),
        total_equity=Decimal("100000"),
        age=30,
        current_values={
            Bucket.CASH: Decimal("10000"),
            Bucket.CORE: Decimal("70000"),
            Bucket.WHEEL: Decimal("16000"),
            Bucket.LEAPS: Decimal("25000"),
        },
    )

    assert recommendation.allocations[Bucket.LEAPS] == Decimal("0.00")
    assert recommendation.allocations[Bucket.WHEEL] == Decimal("0.00")
    assert recommendation.unallocated == Decimal("4000.00")


def test_distribution_rejects_non_positive_profit() -> None:
    with pytest.raises(ValueError, match="可分配收益"):
        recommend_distribution(Decimal("0"), Decimal("100000"), 30, {})
