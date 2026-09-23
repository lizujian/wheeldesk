from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.models import Bucket


class LedgerEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=40)
    bucket: Bucket
    amount: Decimal
    occurred_on: date
    details: dict[str, Any] = Field(default_factory=dict)


class PutOpenCreate(BaseModel):
    trade_date: date
    expiration: date
    strike: Decimal = Field(gt=0)
    premium: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)


class CallOpenCreate(PutOpenCreate):
    pass


class PortfolioInitialize(BaseModel):
    age: int = Field(ge=0, le=100)
    opening_equity: Decimal = Field(gt=0)
    opening_date: date
    allocations: dict[Bucket, Decimal] = Field(default_factory=dict)


class AmountAction(BaseModel):
    amount: Decimal = Field(gt=0)
    date: date
    note: str = ""


class OtherHoldingsUpdate(BaseModel):
    amount: Decimal = Field(ge=0)


class OtherHoldingCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-^]+$")
    quantity: Decimal = Field(gt=0)
    asset_type: Literal["equity", "option"] = "equity"
    direction: Literal["long", "short"] = "long"
    option_type: Literal["call", "put"] | None = None
    entry_price: Decimal | None = Field(default=None, gt=0)
    current_price: Decimal | None = Field(default=None, gt=0)
    opened_on: date | None = None
    expiration: date | None = None
    strike: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_other_contract(self):
        self.symbol = self.symbol.upper()
        if self.asset_type == "equity":
            if any(value is not None for value in (self.option_type, self.expiration, self.strike)):
                raise ValueError("股票不需要期权合约字段")
            if self.direction != "long":
                raise ValueError("其他股票暂不记录做空仓位")
        elif not all((self.option_type, self.expiration, self.strike)):
            raise ValueError("其他期权需要类型、到期日和行权价")
        return self


class OtherHoldingUpdate(BaseModel):
    quantity: Decimal | None = Field(default=None, gt=0)
    entry_price: Decimal | None = Field(default=None, gt=0)
    current_price: Decimal | None = Field(default=None, gt=0)


class OtherHoldingClose(BaseModel):
    date: date
    price: Decimal = Field(gt=0)


class TransferCreate(AmountAction):
    source: Bucket
    target: Bucket


class DateAction(BaseModel):
    date: date


class CloseOptionAction(DateAction):
    premium: Decimal = Field(ge=0)


class CallAwayAction(DateAction):
    pass


class RedistributionRequest(BaseModel):
    distributable_profit: Decimal = Field(gt=0)


class PositionCreate(BaseModel):
    bucket: Bucket
    symbol: str
    asset_type: str
    direction: str = "long"
    option_type: str | None = None
    quantity: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    opened_on: date
    expiration: date | None = None
    strike: Decimal | None = Field(default=None, gt=0)
    delta: Decimal | None = None
    tranche: int | None = Field(default=None, ge=1, le=5)
    core_signal_code: str | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_bucket_contract(self):
        if self.bucket == Bucket.CORE:
            if self.symbol.upper() not in {"BRK.B", "VOO", "SCHD"} or self.asset_type != "equity":
                raise ValueError("核心仓只允许录入 BRK.B、VOO 或 SCHD 正股")
        if self.bucket == Bucket.LEAPS:
            if self.asset_type == "equity":
                if self.symbol.upper() != "QLD" or self.direction.lower() != "long":
                    raise ValueError("LEAPS 替代正股只允许 QLD Long")
                if self.tranche is None:
                    raise ValueError("QLD 替代仓需要选择 LEAPS 批次")
                if any(
                    value is not None
                    for value in (
                        self.expiration,
                        self.strike,
                        self.option_type,
                        self.delta,
                    )
                ):
                    raise ValueError("QLD 正股不需要期权合约参数")
            elif self.asset_type == "option":
                if not all((self.expiration, self.strike, self.tranche)):
                    raise ValueError("LEAPS 需要到期日、行权价和批次")
                from app.domain.leaps import validate_leaps_contract
                from app.domain.trillion_club import is_club_symbol

                symbol = self.symbol.upper()
                if symbol == "TQQQ":
                    raise ValueError("LEAPS 禁止使用 TQQQ")
                if symbol != "QQQ" and not is_club_symbol(symbol):
                    raise ValueError("LEAPS 标的只允许 QQQ 或万亿俱乐部候选股票")
                if symbol != "QQQ":
                    if self.tranche > 2:
                        raise ValueError("万亿俱乐部每只股票最多两个槽位")
                dte = (self.expiration - self.opened_on).days
                validate_leaps_contract(
                    self.symbol,
                    self.option_type or "",
                    self.direction,
                    dte,
                )
            else:
                raise ValueError("LEAPS 只支持 Long Call 或 QLD 正股")
        return self


class PositionMark(BaseModel):
    price: Decimal = Field(gt=0)


class PositionClose(BaseModel):
    date: date
    price: Decimal = Field(gt=0)
    quantity: Decimal | None = Field(default=None, gt=0)


class RebalanceCoreSale(BaseModel):
    date: date
    symbol: Literal["BRK.B", "VOO", "SCHD"] = "BRK.B"
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(gt=0)


class ResetDataRequest(BaseModel):
    confirmation: Literal["RESET"]


ExitPositionType = Literal["stock", "long_call", "sell_put", "covered_call"]


class ExitPositionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    position_type: ExitPositionType
    current_value: Decimal
    target_value: Decimal
    cost_price: Decimal | None = Field(default=None, gt=0)
    note: str = Field(default="", max_length=500)


class ExitPositionUpdate(BaseModel):
    current_value: Decimal | None = None
    target_value: Decimal | None = None
    cost_price: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)


class ExitPositionPartialExit(BaseModel):
    recovered_cash: Decimal = Field(ge=0)
    remaining_value: Decimal
    note: str | None = Field(default=None, max_length=500)


class ExitPositionCompleteExit(BaseModel):
    recovered_cash: Decimal = Field(default=Decimal("0"), ge=0)


class WheelPutCreate(BaseModel):
    symbol: str = Field(default="TQQQ", min_length=1, max_length=20, pattern=r"^[A-Za-z0-9.\-]+$")
    round_id: int | None = Field(default=None, gt=0)
    batch_number: Literal[1, 2]
    trade_date: date
    expiration: date
    strike: Decimal = Field(gt=0)
    premium: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)
    entry_tqqq_price: Decimal = Field(gt=0)
    earnings_confirmed: bool = False

    @model_validator(mode="after")
    def validate_wheel_symbol(self):
        from app.domain.trillion_club import is_wheel_club_symbol

        self.symbol = self.symbol.upper()
        if self.symbol != "TQQQ" and not is_wheel_club_symbol(self.symbol):
            raise ValueError("车轮标的只允许 TQQQ 或万亿俱乐部车轮候选股票")
        if self.symbol != "TQQQ" and self.batch_number != 1:
            raise ValueError("万亿俱乐部个股车轮不拆分第二批")
        if self.symbol != "TQQQ" and not self.earnings_confirmed:
            raise ValueError("个股 Sell Put 需要确认到期日前无财报")
        return self


class WheelPutUpdate(BaseModel):
    trade_date: date | None = None
    expiration: date | None = None
    strike: Decimal | None = Field(default=None, gt=0)
    premium: Decimal | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, gt=0)
    entry_tqqq_price: Decimal | None = Field(default=None, gt=0)


class WheelOptionClose(BaseModel):
    date: date
    premium: Decimal = Field(ge=0)


class WheelPutAssign(BaseModel):
    date: date
    contracts: int = Field(gt=0)


class WheelCallCreate(BaseModel):
    trade_date: date
    expiration: date
    strike: Decimal = Field(gt=0)
    premium: Decimal = Field(gt=0)
    quantity: int = Field(gt=0)


class WheelCallUpdate(BaseModel):
    trade_date: date | None = None
    expiration: date | None = None
    strike: Decimal | None = Field(default=None, gt=0)
    premium: Decimal | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, gt=0)


class WheelCallAway(BaseModel):
    date: date


class WheelVoidRequest(BaseModel):
    confirmation: Literal["VOID"]
    reason: str = Field(min_length=1, max_length=120)


class ProfitRealizedCreate(BaseModel):
    source: Literal["leaps", "other"]
    occurred_on: date
    amount: Decimal
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def reject_zero_amount(self):
        if self.amount == 0:
            raise ValueError("已实现盈亏不能为零")
        return self


class ProfitAllocationCreate(BaseModel):
    occurred_on: date
    amount: Decimal = Field(gt=0)
    allocations: dict[Bucket, Decimal]
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def validate_allocations(self):
        if any(amount < 0 for amount in self.allocations.values()):
            raise ValueError("分配金额不能为负数")
        if sum(self.allocations.values(), Decimal("0")) != self.amount:
            raise ValueError("确认分配金额必须等于各资金桶分配合计")
        return self


class ProfitEntryDelete(BaseModel):
    confirmation: Literal["DELETE"]


class BrokerReportPayload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=10_000_000)


class BrokerImportConfirm(BrokerReportPayload):
    selected_fingerprints: list[str] = Field(min_length=1, max_length=2_000)
    overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    confirmation: Literal["IMPORT"]
