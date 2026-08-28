from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import ExitPositionRecord

POSITION_TYPES = {"stock", "long_call", "sell_put", "covered_call"}
VALUE_TYPES = {"stock", "long_call"}
ZERO = Decimal("0")


class ExitPositionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        name: str,
        position_type: str,
        current_value: Decimal,
        target_value: Decimal,
        note: str = "",
        cost_price: Decimal | None = None,
    ) -> ExitPositionRecord:
        self._validate(position_type, current_value, target_value, cost_price)
        record = ExitPositionRecord(
            name=name.strip(),
            position_type=position_type,
            current_value=current_value,
            target_value=target_value,
            cost_price=cost_price if position_type == "stock" else None,
            note=note.strip(),
            status="active",
            recovered_cash=ZERO,
        )
        if not record.name:
            raise ValueError("名称不能为空")
        self.session.add(record)
        self.session.commit()
        return record

    def update(
        self,
        record_id: int,
        current_value: Decimal | None = None,
        target_value: Decimal | None = None,
        note: str | None = None,
        cost_price: Decimal | None = None,
    ) -> ExitPositionRecord:
        record = self._get_open(record_id)
        next_current = current_value if current_value is not None else record.current_value
        next_target = target_value if target_value is not None else record.target_value
        next_cost_price = cost_price if cost_price is not None else record.cost_price
        self._validate(record.position_type, next_current, next_target, next_cost_price)
        record.current_value = next_current
        record.target_value = next_target
        if record.position_type == "stock" and cost_price is not None:
            record.cost_price = cost_price
        if note is not None:
            record.note = note.strip()
        self.session.commit()
        return record

    def partial_exit(
        self,
        record_id: int,
        recovered_cash: Decimal,
        remaining_value: Decimal,
        note: str | None = None,
    ) -> ExitPositionRecord:
        record = self._get_open(record_id)
        if recovered_cash < ZERO:
            raise ValueError("回收净现金不能为负数")
        self._validate(record.position_type, remaining_value, record.target_value)
        record.current_value = remaining_value
        record.recovered_cash += recovered_cash
        record.status = "partial"
        if note is not None:
            record.note = note.strip()
        self.session.commit()
        return record

    def complete_exit(
        self,
        record_id: int,
        recovered_cash: Decimal = ZERO,
    ) -> ExitPositionRecord:
        record = self._get_open(record_id)
        if recovered_cash < ZERO:
            raise ValueError("回收净现金不能为负数")
        record.current_value = ZERO
        record.recovered_cash += recovered_cash
        record.status = "exited"
        self.session.commit()
        return record

    def list_records(self, include_exited: bool = True) -> list[ExitPositionRecord]:
        statement = select(ExitPositionRecord).order_by(
            ExitPositionRecord.status.asc(),
            ExitPositionRecord.updated_at.desc(),
            ExitPositionRecord.id.desc(),
        )
        if not include_exited:
            statement = statement.where(ExitPositionRecord.status != "exited")
        return list(self.session.scalars(statement))

    def summary(self, records: list[ExitPositionRecord] | None = None) -> dict:
        selected = records if records is not None else self.list_records()
        active = [record for record in selected if record.status != "exited"]
        return {
            "active_count": len(active),
            "target_reached_count": sum(
                1 for record in active if record.current_value >= record.target_value
            ),
            "asset_value": sum(
                (record.current_value for record in active if record.position_type in VALUE_TYPES),
                ZERO,
            ),
            "option_float_pnl": sum(
                (record.current_value for record in active if record.position_type not in VALUE_TYPES),
                ZERO,
            ),
            "recovered_cash": sum((record.recovered_cash for record in selected), ZERO),
        }

    def payload(self, record: ExitPositionRecord) -> dict:
        return {
            "id": record.id,
            "name": record.name,
            "position_type": record.position_type,
            "current_value": record.current_value,
            "target_value": record.target_value,
            "cost_price": record.cost_price,
            "note": record.note,
            "status": record.status,
            "recovered_cash": record.recovered_cash,
            "target_reached": record.status != "exited" and record.current_value >= record.target_value,
            "core_transfer_suggestion": record.recovered_cash,
            "updated_at": record.updated_at,
        }

    def _get_open(self, record_id: int) -> ExitPositionRecord:
        record = self.session.get(ExitPositionRecord, record_id)
        if record is None:
            raise ValueError("找不到待退出仓记录")
        if record.status == "exited":
            raise ValueError("该记录已经全部退出")
        return record

    @staticmethod
    def _validate(
        position_type: str,
        current_value: Decimal,
        target_value: Decimal,
        cost_price: Decimal | None = None,
    ) -> None:
        if position_type not in POSITION_TYPES:
            raise ValueError("不支持的待退出仓类型")
        if position_type in VALUE_TYPES and current_value < ZERO:
            raise ValueError("当前总价值不能为负数")
        if position_type in VALUE_TYPES and target_value < ZERO:
            raise ValueError("目标总价值不能为负数")
        if position_type == "stock" and cost_price is not None and cost_price <= ZERO:
            raise ValueError("每股平均成本价必须大于零")
