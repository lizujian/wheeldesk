from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import BucketBalance, PositionRecord, UnmanagedPositionRecord
from app.domain.pmcc import PMCC_CATEGORIES, build_pmcc_states, summarize_pmcc

ZERO = Decimal("0")


def pmcc_snapshot(
    session: Session,
    *,
    as_of: date | None = None,
    underlying_prices: dict[str, Decimal] | None = None,
) -> dict:
    positions = list(
        session.scalars(
            select(PositionRecord).where(
                PositionRecord.bucket == "leaps",
                PositionRecord.status == "open",
            )
        )
    )
    calls = list(
        session.scalars(
            select(UnmanagedPositionRecord).where(
                UnmanagedPositionRecord.category.in_(PMCC_CATEGORIES),
                UnmanagedPositionRecord.asset_type == "option",
                UnmanagedPositionRecord.option_type == "call",
            )
        )
    )
    total_equity = sum(
        (row.amount for row in session.scalars(select(BucketBalance))),
        ZERO,
    )
    result = summarize_pmcc(
        build_pmcc_states(
            positions,
            calls,
            as_of=as_of or date.today(),
            underlying_prices=underlying_prices,
        ),
        total_equity,
    )
    closed_calls = [
        call for call in calls if call.status == "closed" and call.realized_profit is not None
    ]
    result["realized_profit"] = sum(
        (call.realized_profit for call in closed_calls), ZERO
    ).quantize(Decimal("0.01"))
    result["closed_short_call_count"] = len(closed_calls)
    result["short_call_realized_by_symbol"] = _realized_by_symbol(closed_calls)
    return result


def _realized_by_symbol(records: list[UnmanagedPositionRecord]) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    for record in records:
        values[record.symbol] = (
            values.get(record.symbol, ZERO) + (record.realized_profit or ZERO)
        ).quantize(Decimal("0.01"))
    return values
