from decimal import Decimal
from typing import Mapping

from app.domain.models import Bucket

ZERO = Decimal("0")


def allocation_targets(age: int) -> dict[Bucket, Decimal]:
    if not 0 <= age <= 100:
        raise ValueError("年龄必须在 0 到 100 之间")

    # Keep the account-level risk budget stable. Wheel and LEAPS remain
    # separate operational buckets, but their target is one shared 25% pool.
    core = Decimal("0.70")
    cash = Decimal("0.05")
    leaps = Decimal("0.25")
    return {
        Bucket.CORE: core,
        Bucket.CASH: cash,
        Bucket.WHEEL: ZERO,
        Bucket.LEAPS: leaps,
    }


def opening_allocation(
    opening_equity: Decimal,
    assigned: Mapping[Bucket, Decimal],
) -> dict[Bucket, Decimal]:
    if opening_equity < ZERO:
        raise ValueError("初始总金额不能为负数")
    if any(value < ZERO for value in assigned.values()):
        raise ValueError("资金桶金额不能为负数")

    result = {bucket: ZERO for bucket in Bucket}
    for bucket, value in assigned.items():
        result[bucket] += value

    assigned_total = sum(result.values(), ZERO)
    if assigned_total > opening_equity:
        raise ValueError("已分配金额超过初始总金额")
    result[Bucket.UNALLOCATED] += opening_equity - assigned_total
    return result
