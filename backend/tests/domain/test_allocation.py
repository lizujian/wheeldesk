from decimal import Decimal

import pytest

from app.domain.allocation import allocation_targets, opening_allocation
from app.domain.models import Bucket


def test_allocation_targets_use_seventy_twenty_five_five_for_age_30() -> None:
    targets = allocation_targets(age=30)

    assert targets == {
        Bucket.CORE: Decimal("0.70"),
        Bucket.CASH: Decimal("0.05"),
        Bucket.WHEEL: Decimal("0.00"),
        Bucket.LEAPS: Decimal("0.25"),
    }


def test_allocation_targets_are_stable_across_age() -> None:
    targets = allocation_targets(age=36)

    assert targets == {
        Bucket.CORE: Decimal("0.70"),
        Bucket.CASH: Decimal("0.05"),
        Bucket.WHEEL: Decimal("0.00"),
        Bucket.LEAPS: Decimal("0.25"),
    }


def test_allocation_targets_are_stable_at_high_age() -> None:
    targets = allocation_targets(age=70)

    assert targets == {
        Bucket.CORE: Decimal("0.70"),
        Bucket.CASH: Decimal("0.05"),
        Bucket.WHEEL: Decimal("0.00"),
        Bucket.LEAPS: Decimal("0.25"),
    }


def test_opening_allocation_preserves_unallocated_difference() -> None:
    result = opening_allocation(
        opening_equity=Decimal("100000"),
        assigned={Bucket.CORE: Decimal("45000"), Bucket.CASH: Decimal("10000")},
    )

    assert result[Bucket.UNALLOCATED] == Decimal("45000")
    assert sum(result.values()) == Decimal("100000")


def test_opening_allocation_rejects_values_above_opening_equity() -> None:
    with pytest.raises(ValueError, match="超过初始总金额"):
        opening_allocation(
            opening_equity=Decimal("100"),
            assigned={Bucket.CORE: Decimal("101")},
        )
