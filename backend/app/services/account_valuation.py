"""Keep statement NAV and unexplained valuation differences out of cash."""
from decimal import Decimal

from sqlalchemy import select

from app.db_models import BrokerAccountSnapshot, BucketBalance, PositionRecord, UnmanagedPositionRecord, WheelCallLot, WheelPutLot

ZERO = Decimal("0")
CENT = Decimal("0.01")


class AccountValuationService:
    def __init__(self, session):
        self.session = session

    def unrealized(self) -> dict[str, Decimal]:
        result = dict.fromkeys(("core", "leaps", "wheel", "other"), ZERO)
        for row in self.session.scalars(select(PositionRecord).where(PositionRecord.status == "open")):
            result[row.bucket] = result.get(row.bucket, ZERO) + (row.current_price - row.entry_price) * row.quantity * row.multiplier
        for model, quantity_field in ((WheelPutLot, "open_quantity"), (WheelCallLot, "quantity")):
            for row in self.session.scalars(select(model).where(model.state == "open")):
                if row.quote_ask is not None:
                    bucket = "core" if getattr(row, "capital_bucket", None) == "core" else "wheel"
                    result[bucket] += (row.premium - row.quote_ask) * 100 * getattr(row, quantity_field)
        for row in self.session.scalars(select(UnmanagedPositionRecord).where(UnmanagedPositionRecord.status == "open")):
            if row.current_price is None or row.entry_price is None:
                continue
            bucket = "leaps" if row.category in {"pmcc", "leaps_call_wheel"} else "other"
            sign = 1 if row.direction == "long" else -1
            result[bucket] += (row.current_price - row.entry_price) * row.quantity * row.multiplier * sign
        return {key: amount.quantize(CENT) for key, amount in result.items()}

    def snapshot(self) -> dict:
        ledger_equity = sum((row.amount for row in self.session.scalars(select(BucketBalance))), ZERO)
        unrealized = self.unrealized()
        reported = self.session.get(BrokerAccountSnapshot, 1)
        adjustment = reported.valuation_adjustment if reported else ZERO
        return {
            "ledger_equity": ledger_equity,
            "unrealized": unrealized,
            "valuation_adjustment": adjustment,
            "economic_equity": (ledger_equity + sum(unrealized.values(), ZERO) + adjustment).quantize(CENT),
            "broker_net_asset_value": reported.net_asset_value if reported else None,
            "broker_report_as_of": reported.report_as_of if reported else None,
        }
