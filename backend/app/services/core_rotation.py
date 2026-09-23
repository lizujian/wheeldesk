from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import CoreTradeRecord, LedgerEvent
from app.domain.core import CORE_ROTATION_SYMBOLS
from app.domain.core_rotation import RULES, RotationUsage

ZERO = Decimal("0")


class CoreRotationService:
    def __init__(self, session: Session):
        self.session = session

    def usage(self, prices: dict[str, dict[date, Decimal]]) -> tuple[RotationUsage, list[dict]]:
        days = sorted(set.intersection(*(set(prices[symbol]) for symbol in CORE_ROTATION_SYMBOLS)))
        if len(days) < RULES.window_sessions:
            return RotationUsage(complete=False), []
        window = days[-RULES.window_sessions:]
        records = list(self.session.scalars(select(CoreTradeRecord).order_by(CoreTradeRecord.traded_at)))
        used = ZERO
        complete = True
        executions = []
        for record in records:
            traded_on = record.traded_at.date()
            if record.quantity >= ZERO or not window[0] <= traded_on <= window[-1]:
                continue
            pre = record.pre_quantities
            prices_on_trade = {
                symbol: record.price if record.symbol == symbol else prices[symbol].get(traded_on)
                for symbol in CORE_ROTATION_SYMBOLS
            }
            fraction = None
            if pre and all(price is not None and price > ZERO for price in prices_on_trade.values()):
                total = sum(
                    (Decimal(str(pre.get(symbol, "0"))) * prices_on_trade[symbol]
                     for symbol in CORE_ROTATION_SYMBOLS),
                    ZERO,
                )
                if total > ZERO:
                    fraction = abs(record.quantity) * record.price / total
            if fraction is None:
                complete = False
            else:
                used += fraction
            executions.append({
                "id": record.id, "symbol": record.symbol, "traded_at": record.traded_at.isoformat(),
                "quantity": abs(record.quantity), "price": record.price,
                "proceeds": abs(record.quantity) * record.price, "weight_change": fraction,
            })
        # Legacy snapshot reductions without execution details must not imply unused capacity.
        legacy = self.session.scalars(select(LedgerEvent).where(
            LedgerEvent.event_type.in_(("core_rotation_leg", "core_rebalance_sale")),
            LedgerEvent.occurred_on >= window[0], LedgerEvent.occurred_on <= window[-1],
        ))
        for event in legacy:
            recorded_sold = sum((abs(record.quantity) for record in records
                                 if record.symbol == event.details.get("symbol") and record.quantity < ZERO
                                 and record.traded_at.date() == event.occurred_on), ZERO)
            expected_sold = (
                Decimal(str(event.details.get("previous_quantity", 0))) - Decimal(str(event.details.get("quantity", 0)))
                if event.event_type == "core_rotation_leg" else Decimal(str(event.details.get("quantity", 0)))
            )
            if recorded_sold <= ZERO or recorded_sold < expected_sold:
                complete = False
        return RotationUsage(used_weight=used, complete=complete), executions
