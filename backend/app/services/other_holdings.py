from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import PortfolioProfile, UnmanagedPositionRecord
from app.domain.leaps import LEAPS_CALL_WHEEL_CATEGORY

ZERO = Decimal("0")
BOXX = "BOXX"


class OtherHoldingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        symbol: str,
        quantity: Decimal,
        *,
        asset_type: str = "equity",
        direction: str = "long",
        option_type: str | None = None,
        entry_price: Decimal | None = None,
        current_price: Decimal | None = None,
        opened_on: date | None = None,
        expiration: date | None = None,
        strike: Decimal | None = None,
    ) -> dict:
        self._require_profile()
        normalized = symbol.upper()
        self._ensure_unique_contract(
            normalized, asset_type, direction, option_type, expiration, strike
        )
        record = UnmanagedPositionRecord(
            category="cash_equivalent" if normalized == BOXX and asset_type == "equity" else "other",
            symbol=normalized,
            asset_type=asset_type,
            direction=direction,
            option_type=option_type,
            quantity=quantity,
            multiplier=100 if asset_type == "option" else 1,
            entry_price=entry_price,
            current_price=current_price or entry_price,
            opened_on=opened_on,
            expiration=expiration,
            strike=strike,
            status="open",
        )
        self.session.add(record)
        self.session.commit()
        return self.payload(record)

    def update(
        self,
        record_id: int,
        *,
        quantity: Decimal | None = None,
        entry_price: Decimal | None = None,
        current_price: Decimal | None = None,
    ) -> dict:
        record = self._get(record_id)
        if record.status != "open":
            raise ValueError("该持仓已经退出")
        if quantity is not None:
            record.quantity = quantity
        if entry_price is not None:
            record.entry_price = entry_price
        if current_price is not None:
            record.current_price = current_price
            record.quote_source = "manual"
            record.quote_as_of = date.today()
            record.last_error = None
        self.session.commit()
        return self.payload(record)

    def close(self, record_id: int, closed_on: date, price: Decimal) -> dict:
        record = self._get(record_id)
        if record.status != "open":
            raise ValueError("该持仓已经退出")
        record.current_price = price
        record.exit_price = price
        record.closed_on = closed_on
        record.status = "closed"
        if record.entry_price is not None:
            signed = Decimal("1") if record.direction == "long" else Decimal("-1")
            record.realized_profit = (
                (price - record.entry_price)
                * record.quantity
                * record.multiplier
                * signed
            ).quantize(Decimal("0.01"))
        self.session.commit()
        return self.payload(record)

    def delete(self, record_id: int) -> None:
        record = self._get(record_id)
        self.session.delete(record)
        self.session.commit()

    def listing(self, include_closed: bool = False) -> dict:
        statement = select(UnmanagedPositionRecord).order_by(
            UnmanagedPositionRecord.category.asc(),
            UnmanagedPositionRecord.symbol.asc(),
            UnmanagedPositionRecord.expiration.asc(),
            UnmanagedPositionRecord.strike.asc(),
        )
        if not include_closed:
            statement = statement.where(UnmanagedPositionRecord.status == "open")
        records = list(self.session.scalars(statement))
        strategy_records = [
            record for record in records if record.category == LEAPS_CALL_WHEEL_CATEGORY
        ]
        records = [
            record for record in records if record.category != LEAPS_CALL_WHEEL_CATEGORY
        ]
        open_records = [record for record in records if record.status == "open"]
        return {
            "records": [self.payload(record) for record in records],
            "leaps_call_wheels": [self.payload(record) for record in strategy_records],
            "total_value": sum(
                (self._signed_value(record) for record in open_records), ZERO
            ).quantize(Decimal("0.01")),
            "cash_equivalent_value": sum(
                (
                    self._signed_value(record)
                    for record in open_records
                    if record.category == "cash_equivalent"
                ),
                ZERO,
            ).quantize(Decimal("0.01")),
            "other_value": sum(
                (
                    self._signed_value(record)
                    for record in open_records
                    if record.category == "other"
                ),
                ZERO,
            ).quantize(Decimal("0.01")),
            "unpriced_count": sum(record.current_price is None for record in open_records),
        }

    @classmethod
    def payload(cls, record: UnmanagedPositionRecord) -> dict:
        absolute_value = (
            (record.current_price * record.quantity * record.multiplier).quantize(Decimal("0.01"))
            if record.current_price is not None
            else None
        )
        signed_value = (
            absolute_value if record.direction == "long" else -absolute_value
            if absolute_value is not None
            else None
        )
        unrealized = None
        if record.entry_price is not None and record.current_price is not None and record.status == "open":
            signed = Decimal("1") if record.direction == "long" else Decimal("-1")
            unrealized = (
                (record.current_price - record.entry_price)
                * record.quantity
                * record.multiplier
                * signed
            ).quantize(Decimal("0.01"))
        quote_status = "updated"
        if record.current_price is None:
            quote_status = "unavailable"
        elif record.last_error:
            quote_status = "stale"
        return {
            "id": record.id,
            "category": record.category,
            "symbol": record.symbol,
            "asset_type": record.asset_type,
            "direction": record.direction,
            "option_type": record.option_type,
            "quantity": record.quantity,
            "multiplier": record.multiplier,
            "entry_price": record.entry_price,
            "current_price": record.current_price,
            "current_value": signed_value,
            "absolute_value": absolute_value,
            "unrealized_profit": unrealized,
            "opened_on": record.opened_on,
            "expiration": record.expiration,
            "strike": record.strike,
            "status": record.status,
            "closed_on": record.closed_on,
            "exit_price": record.exit_price,
            "realized_profit": record.realized_profit,
            "quote_source": record.quote_source,
            "quote_as_of": record.quote_as_of,
            "quote_status": quote_status,
            "last_error": record.last_error,
            "linked_position_id": record.linked_position_id,
        }

    @staticmethod
    def _signed_value(record: UnmanagedPositionRecord) -> Decimal:
        if record.current_price is None:
            return ZERO
        value = record.current_price * record.quantity * record.multiplier
        return value if record.direction == "long" else -value

    def _ensure_unique_contract(
        self,
        symbol: str,
        asset_type: str,
        direction: str,
        option_type: str | None,
        expiration: date | None,
        strike: Decimal | None,
    ) -> None:
        existing = self.session.scalar(
            select(UnmanagedPositionRecord.id).where(
                UnmanagedPositionRecord.status == "open",
                UnmanagedPositionRecord.symbol == symbol,
                UnmanagedPositionRecord.asset_type == asset_type,
                UnmanagedPositionRecord.direction == direction,
                UnmanagedPositionRecord.option_type == option_type,
                UnmanagedPositionRecord.expiration == expiration,
                UnmanagedPositionRecord.strike == strike,
            )
        )
        if existing is not None:
            raise ValueError("该其他持仓合约已经存在，请直接更新")

    def _get(self, record_id: int) -> UnmanagedPositionRecord:
        record = self.session.get(UnmanagedPositionRecord, record_id)
        if record is None:
            raise ValueError("找不到其他持仓记录")
        return record

    def _require_profile(self) -> None:
        if self.session.get(PortfolioProfile, 1) is None:
            raise ValueError("请先初始化账户")
