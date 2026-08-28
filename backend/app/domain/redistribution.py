from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from app.domain.allocation import allocation_targets
from app.domain.models import Bucket

ZERO = Decimal("0")
CENT = Decimal("0.01")


@dataclass(frozen=True)
class DistributionRecommendation:
    allocations: dict[Bucket, Decimal]
    unallocated: Decimal


def recommend_distribution(
    distributable_profit: Decimal,
    total_equity: Decimal,
    age: int,
    current_values: Mapping[Bucket, Decimal],
) -> DistributionRecommendation:
    if distributable_profit <= ZERO:
        raise ValueError("可分配收益必须大于零")
    if total_equity <= ZERO:
        raise ValueError("总资产必须大于零")

    target_fractions = allocation_targets(age)
    targets = {bucket: total_equity * fraction for bucket, fraction in target_fractions.items()}
    gaps = {
        bucket: max(target - current_values.get(bucket, ZERO), ZERO)
        for bucket, target in targets.items()
    }
    allocations = {bucket: ZERO.quantize(CENT) for bucket in target_fractions}
    remaining = distributable_profit

    for bucket in (Bucket.CASH, Bucket.CORE):
        amount = min(remaining, gaps[bucket])
        allocations[bucket] = amount.quantize(CENT)
        remaining -= amount

    option_target = targets[Bucket.WHEEL] + targets[Bucket.LEAPS]
    option_current = current_values.get(Bucket.WHEEL, ZERO) + current_values.get(
        Bucket.LEAPS, ZERO
    )
    option_gap = max(option_target - option_current, ZERO)
    option_budget = min(remaining, option_gap)
    if option_budget > ZERO:
        # Wheel is the storage bucket for newly allocated shared option principal;
        # both Wheel and LEAPS consume the combined balance.
        allocations[Bucket.WHEEL] = option_budget.quantize(CENT)
        remaining -= option_budget

    return DistributionRecommendation(
        allocations=allocations,
        unallocated=remaining.quantize(CENT),
    )
