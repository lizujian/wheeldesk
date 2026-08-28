from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import LedgerEvent, WheelCycle
from app.domain.models import Bucket

MULTIPLIER = Decimal("100")


class WheelCycleService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def open_put(
        self,
        trade_date: date,
        expiration: date,
        strike: Decimal,
        premium: Decimal,
        quantity: int,
    ) -> WheelCycle:
        if expiration <= trade_date:
            raise ValueError("到期日必须晚于交易日")
        if strike <= 0 or premium <= 0 or quantity <= 0:
            raise ValueError("Put 开仓参数无效")
        active = self.session.scalar(select(WheelCycle).where(WheelCycle.state != "closed"))
        if active is not None:
            raise ValueError("已有未完成的车轮周期")
        premium_net = premium * MULTIPLIER * quantity
        cycle = WheelCycle(
            state="put_open",
            opened_on=trade_date,
            put_expiration=expiration,
            put_strike=strike,
            put_premium=premium,
            put_quantity=quantity,
            put_fees=Decimal("0"),
            put_premium_net=premium_net,
        )
        self.session.add(cycle)
        self.session.flush()
        self._event(cycle.id, "put_open", premium_net, trade_date)
        self.session.commit()
        return cycle

    def assign_put(self, cycle_id: int, assigned_on: date) -> WheelCycle:
        cycle = self._require(cycle_id, "put_open")
        shares = cycle.put_quantity * 100
        gross_cost = cycle.put_strike * shares
        cycle.state = "shares_held"
        cycle.share_quantity = shares
        cycle.share_cost_total = gross_cost - cycle.put_premium_net
        self._event(cycle.id, "put_assigned", -gross_cost, assigned_on)
        self.session.commit()
        return cycle

    def expire_put(self, cycle_id: int, expired_on: date) -> WheelCycle:
        cycle = self._require(cycle_id, "put_open")
        cycle.state = "closed"
        cycle.closed_on = expired_on
        cycle.realized_profit = cycle.put_premium_net
        self._event(cycle.id, "put_expired", Decimal("0"), expired_on)
        self.session.commit()
        return cycle

    def close_put(
        self,
        cycle_id: int,
        closed_on: date,
        buyback_premium: Decimal,
    ) -> WheelCycle:
        cycle = self._require(cycle_id, "put_open")
        if buyback_premium < 0:
            raise ValueError("Put 平仓金额不能为负数")
        close_cost = buyback_premium * MULTIPLIER * cycle.put_quantity
        cycle.state = "closed"
        cycle.closed_on = closed_on
        cycle.realized_profit = cycle.put_premium_net - close_cost
        self._event(cycle.id, "put_closed", -close_cost, closed_on)
        self.session.commit()
        return cycle

    def open_call(
        self,
        cycle_id: int,
        trade_date: date,
        expiration: date,
        strike: Decimal,
        premium: Decimal,
        quantity: int,
    ) -> WheelCycle:
        cycle = self._require(cycle_id, "shares_held")
        if expiration <= trade_date:
            raise ValueError("到期日必须晚于交易日")
        if quantity <= 0 or quantity * 100 > cycle.share_quantity:
            raise ValueError("Covered Call 数量超过持股覆盖范围")
        premium_net = premium * MULTIPLIER * quantity
        cycle.state = "call_open"
        cycle.call_expiration = expiration
        cycle.call_strike = strike
        cycle.call_premium = premium
        cycle.call_quantity = quantity
        cycle.call_fees = Decimal("0")
        cycle.call_premium_net += premium_net
        self._event(cycle.id, "call_open", premium_net, trade_date)
        self.session.commit()
        return cycle

    def expire_call(self, cycle_id: int, expired_on: date) -> WheelCycle:
        cycle = self._require(cycle_id, "call_open")
        cycle.state = "shares_held"
        cycle.call_expiration = None
        cycle.call_strike = None
        cycle.call_premium = None
        cycle.call_quantity = 0
        self._event(cycle.id, "call_expired", Decimal("0"), expired_on)
        self.session.commit()
        return cycle

    def close_call(
        self,
        cycle_id: int,
        closed_on: date,
        buyback_premium: Decimal,
    ) -> WheelCycle:
        cycle = self._require(cycle_id, "call_open")
        if buyback_premium < 0:
            raise ValueError("Call 平仓金额不能为负数")
        close_cost = buyback_premium * MULTIPLIER * cycle.call_quantity
        cycle.call_premium_net -= close_cost
        cycle.state = "shares_held"
        cycle.call_expiration = None
        cycle.call_strike = None
        cycle.call_premium = None
        cycle.call_quantity = 0
        self._event(cycle.id, "call_closed", -close_cost, closed_on)
        self.session.commit()
        return cycle

    def call_away(
        self,
        cycle_id: int,
        assigned_on: date,
    ) -> WheelCycle:
        cycle = self._require(cycle_id, "call_open")
        assert cycle.call_strike is not None
        proceeds = cycle.call_strike * cycle.share_quantity
        gross_assigned_cost = cycle.put_strike * cycle.share_quantity
        cycle.realized_profit = (
            proceeds
            - gross_assigned_cost
            + cycle.put_premium_net
            + cycle.call_premium_net
        )
        cycle.state = "closed"
        cycle.closed_on = assigned_on
        self._event(cycle.id, "shares_called_away", proceeds, assigned_on)
        self.session.commit()
        return cycle

    def current(self) -> WheelCycle | None:
        return self.session.scalar(
            select(WheelCycle).where(WheelCycle.state != "closed").order_by(WheelCycle.id.desc())
        )

    def _require(self, cycle_id: int, state: str) -> WheelCycle:
        cycle = self.session.get(WheelCycle, cycle_id)
        if cycle is None:
            raise ValueError("找不到车轮周期")
        if cycle.state != state:
            raise ValueError(f"当前状态 {cycle.state} 不允许该操作")
        return cycle

    def _event(self, cycle_id: int, event_type: str, amount: Decimal, occurred_on: date) -> None:
        self.session.add(
            LedgerEvent(
                event_type=event_type,
                bucket=Bucket.WHEEL.value,
                amount=amount,
                occurred_on=occurred_on,
                details={},
                wheel_cycle_id=cycle_id,
            )
        )
