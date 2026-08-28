from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db_models import (
    BucketBalance,
    WheelCallLot,
    WheelPutLot,
    WheelRound,
    WheelShareLot,
)
from app.domain.wheel_portfolio import (
    annualized_return,
    budget_status,
    recommend_batches,
)
from app.domain.models import Bucket
from app.domain.trillion_club import is_wheel_club_symbol
from app.services.portfolio_store import PortfolioStore
from app.services.realized_cash import RealizedCashService
from app.services.capital_accounting import CapitalAccountingService

ZERO = Decimal("0")
HUNDRED = Decimal("100")


class WheelPortfolioService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def open_put(
        self,
        batch_number: int,
        trade_date: date,
        expiration: date,
        strike: Decimal,
        premium: Decimal,
        quantity: int,
        entry_tqqq_price: Decimal,
        round_id: int | None = None,
        symbol: str = "TQQQ",
        earnings_confirmed: bool = False,
        broker_reconciled: bool = False,
    ) -> WheelPutLot:
        symbol = symbol.upper()
        self._validate_option(trade_date, expiration, strike, premium, quantity)
        if symbol != "TQQQ" and not is_wheel_club_symbol(symbol):
            raise ValueError("车轮标的只允许 TQQQ 或万亿俱乐部车轮候选股票")
        if symbol != "TQQQ" and not earnings_confirmed and not broker_reconciled:
            raise ValueError("个股 Sell Put 需要确认到期日前无财报")
        if symbol != "TQQQ" and self.has_exposure(symbol) and round_id is None and not broker_reconciled:
            raise ValueError(f"{symbol} 已有活动车轮周期")
        if batch_number not in (1, 2):
            raise ValueError("车轮批次只能是第一批或第二批")
        if symbol != "TQQQ" and batch_number != 1:
            raise ValueError("万亿俱乐部个股车轮不拆分第二批")
        if round_id is None:
            if batch_number != 1:
                raise ValueError("第二批必须关联已有轮次")
            next_number = int(
                self.session.scalar(select(func.coalesce(func.max(WheelRound.number), 0))) or 0
            ) + 1
            round_record = WheelRound(number=next_number, opened_on=trade_date, status="active")
            self.session.add(round_record)
            self.session.flush()
        else:
            round_record = self._round(round_id)
            if round_record.status != "active":
                raise ValueError("该轮次已经结束")
            if batch_number == 2:
                first = self.session.scalar(
                    select(WheelPutLot).where(
                        WheelPutLot.round_id == round_id,
                        WheelPutLot.batch_number == 1,
                        WheelPutLot.state != "voided",
                    )
                )
                if first is None:
                    raise ValueError("第二批必须先有第一批")
                if first.symbol != symbol:
                    raise ValueError("第二批必须与第一批使用相同标的")
                if trade_date <= first.trade_date:
                    raise ValueError("第二批交易日必须晚于第一批")
        record = WheelPutLot(
            round_id=round_record.id,
            symbol=symbol,
            batch_number=batch_number,
            trade_date=trade_date,
            expiration=expiration,
            strike=strike,
            premium=premium,
            quantity=quantity,
            open_quantity=quantity,
            assigned_contracts=0,
            entry_tqqq_price=entry_tqqq_price,
            earnings_confirmed=earnings_confirmed,
            state="open",
            realized_profit=ZERO,
        )
        self.session.add(record)
        self.session.commit()
        return record

    def edit_put(
        self,
        put_id: int,
        *,
        trade_date: date | None = None,
        expiration: date | None = None,
        strike: Decimal | None = None,
        premium: Decimal | None = None,
        quantity: int | None = None,
        entry_tqqq_price: Decimal | None = None,
    ) -> WheelPutLot:
        record = self._put(put_id)
        if record.state != "open" or record.assigned_contracts:
            raise ValueError("只有未产生后续记录的 Put 可以编辑")
        next_trade = trade_date or record.trade_date
        next_expiration = expiration or record.expiration
        next_strike = strike if strike is not None else record.strike
        next_premium = premium if premium is not None else record.premium
        next_quantity = quantity if quantity is not None else record.quantity
        self._validate_option(
            next_trade, next_expiration, next_strike, next_premium, next_quantity
        )
        record.trade_date = next_trade
        record.expiration = next_expiration
        record.strike = next_strike
        record.premium = next_premium
        record.quantity = next_quantity
        record.open_quantity = next_quantity
        if entry_tqqq_price is not None:
            if entry_tqqq_price <= ZERO:
                raise ValueError("TQQQ 开仓价格必须大于零")
            record.entry_tqqq_price = entry_tqqq_price
        self.session.commit()
        return record

    def close_put(self, put_id: int, closed_on: date, buyback_premium: Decimal) -> WheelPutLot:
        record = self._require_put_open(put_id)
        if buyback_premium < ZERO:
            raise ValueError("买回权利金不能为负数")
        contracts = record.open_quantity
        profit = (record.premium - buyback_premium) * HUNDRED * contracts
        record.realized_profit += profit
        record.open_quantity = 0
        record.state = "closed"
        record.closed_on = closed_on
        record.close_premium = buyback_premium
        self._refresh_round(record.round_id)
        self._post_profit(f"wheel-put:{record.id}", profit, closed_on)
        self.session.commit()
        return record

    def roll_put(
        self,
        put_id: int,
        *,
        rolled_on: date,
        buyback_premium: Decimal,
        expiration: date,
        strike: Decimal,
        premium: Decimal,
        quantity: int,
        entry_underlying_price: Decimal | None = None,
    ) -> WheelPutLot:
        previous = self._require_put_open(put_id)
        if quantity != previous.open_quantity:
            raise ValueError("当前仅支持整笔 Sell Put 展期")
        self._validate_option(rolled_on, expiration, strike, premium, quantity)
        if expiration <= previous.expiration:
            raise ValueError("展期后的到期日必须晚于旧合约")

        existing = self.session.scalar(
            select(WheelPutLot).where(WheelPutLot.rolled_from_put_id == previous.id)
        )
        if existing is not None:
            return existing

        if buyback_premium < ZERO:
            raise ValueError("旧合约买回价格不能为负数")

        profit = (previous.premium - buyback_premium) * HUNDRED * quantity
        previous.realized_profit += profit
        previous.open_quantity = 0
        previous.state = "rolled"
        previous.closed_on = rolled_on
        previous.close_premium = buyback_premium

        next_put = WheelPutLot(
            round_id=previous.round_id,
            rolled_from_put_id=previous.id,
            symbol=previous.symbol,
            batch_number=previous.batch_number,
            trade_date=rolled_on,
            expiration=expiration,
            strike=strike,
            premium=premium,
            quantity=quantity,
            open_quantity=quantity,
            assigned_contracts=0,
            entry_tqqq_price=entry_underlying_price or previous.entry_tqqq_price,
            earnings_confirmed=previous.earnings_confirmed,
            state="open",
            realized_profit=ZERO,
        )
        self.session.add(next_put)
        self.session.flush()
        self._refresh_round(previous.round_id)
        self._post_profit(f"wheel-put:{previous.id}", profit, rolled_on)
        self.session.commit()
        return next_put

    def expire_put(self, put_id: int, expired_on: date) -> WheelPutLot:
        record = self._require_put_open(put_id)
        profit = record.premium * HUNDRED * record.open_quantity
        record.realized_profit += profit
        record.open_quantity = 0
        record.state = "expired"
        record.closed_on = expired_on
        record.close_premium = ZERO
        self._refresh_round(record.round_id)
        self._post_profit(f"wheel-put:{record.id}", profit, expired_on)
        self.session.commit()
        return record

    def assign_put(self, put_id: int, assigned_on: date, contracts: int) -> WheelShareLot:
        record = self._require_put_open(put_id)
        if contracts <= 0 or contracts > record.open_quantity:
            raise ValueError("行权合约数量无效")
        shares = contracts * 100
        share_lot = WheelShareLot(
            put_lot_id=record.id,
            assigned_on=assigned_on,
            assignment_strike=record.strike,
            original_quantity=shares,
            remaining_quantity=shares,
            state="held",
            realized_profit=ZERO,
        )
        record.open_quantity -= contracts
        record.assigned_contracts += contracts
        record.realized_profit += record.premium * HUNDRED * contracts
        if record.open_quantity == 0:
            record.state = "assigned"
            record.closed_on = assigned_on
        self.session.add(share_lot)
        self.session.flush()
        self._post_profit(
            f"wheel-put-assignment:{share_lot.id}",
            record.premium * HUNDRED * contracts,
            assigned_on,
        )
        self.session.commit()
        return share_lot

    def open_call(
        self,
        share_lot_id: int,
        trade_date: date,
        expiration: date,
        strike: Decimal,
        premium: Decimal,
        quantity: int,
    ) -> WheelCallLot:
        self._validate_option(trade_date, expiration, strike, premium, quantity)
        shares = self._share(share_lot_id)
        if shares.state != "held":
            raise ValueError("该持股批次不能开 Covered Call")
        open_calls = self.session.scalar(
            select(func.coalesce(func.sum(WheelCallLot.quantity), 0)).where(
                WheelCallLot.share_lot_id == share_lot_id,
                WheelCallLot.state == "open",
            )
        )
        if (int(open_calls or 0) + quantity) * 100 > shares.remaining_quantity:
            raise ValueError("Covered Call 数量超过可覆盖股数")
        record = WheelCallLot(
            share_lot_id=share_lot_id,
            trade_date=trade_date,
            expiration=expiration,
            strike=strike,
            premium=premium,
            quantity=quantity,
            state="open",
            realized_profit=ZERO,
        )
        self.session.add(record)
        self.session.commit()
        return record

    def edit_call(
        self,
        call_id: int,
        *,
        trade_date: date | None = None,
        expiration: date | None = None,
        strike: Decimal | None = None,
        premium: Decimal | None = None,
        quantity: int | None = None,
    ) -> WheelCallLot:
        record = self._require_call_open(call_id)
        next_trade = trade_date or record.trade_date
        next_expiration = expiration or record.expiration
        next_strike = strike if strike is not None else record.strike
        next_premium = premium if premium is not None else record.premium
        next_quantity = quantity if quantity is not None else record.quantity
        self._validate_option(
            next_trade, next_expiration, next_strike, next_premium, next_quantity
        )
        shares = self._share(record.share_lot_id)
        other_calls = self.session.scalar(
            select(func.coalesce(func.sum(WheelCallLot.quantity), 0)).where(
                WheelCallLot.share_lot_id == record.share_lot_id,
                WheelCallLot.state == "open",
                WheelCallLot.id != record.id,
            )
        )
        if (int(other_calls or 0) + next_quantity) * 100 > shares.remaining_quantity:
            raise ValueError("Covered Call 数量超过可覆盖股数")
        record.trade_date = next_trade
        record.expiration = next_expiration
        record.strike = next_strike
        record.premium = next_premium
        record.quantity = next_quantity
        self.session.commit()
        return record

    def close_call(self, call_id: int, closed_on: date, buyback_premium: Decimal) -> WheelCallLot:
        record = self._require_call_open(call_id)
        if buyback_premium < ZERO:
            raise ValueError("买回权利金不能为负数")
        record.realized_profit = (
            record.premium - buyback_premium
        ) * HUNDRED * record.quantity
        record.state = "closed"
        record.closed_on = closed_on
        record.close_premium = buyback_premium
        self._refresh_round_for_call(record)
        self._post_profit(
            f"wheel-call:{record.id}", record.realized_profit, closed_on
        )
        self.session.commit()
        return record

    def expire_call(self, call_id: int, expired_on: date) -> WheelCallLot:
        record = self._require_call_open(call_id)
        record.realized_profit = record.premium * HUNDRED * record.quantity
        record.state = "expired"
        record.closed_on = expired_on
        record.close_premium = ZERO
        self._refresh_round_for_call(record)
        self._post_profit(
            f"wheel-call:{record.id}", record.realized_profit, expired_on
        )
        self.session.commit()
        return record

    def call_away(self, call_id: int, assigned_on: date) -> WheelCallLot:
        call = self._require_call_open(call_id)
        shares = self._share(call.share_lot_id)
        called_shares = call.quantity * 100
        if called_shares > shares.remaining_quantity:
            raise ValueError("扣走股数超过当前持股")
        call.realized_profit = (
            (call.strike - shares.assignment_strike) * called_shares
            + call.premium * HUNDRED * call.quantity
        )
        call.state = "called_away"
        call.closed_on = assigned_on
        shares.remaining_quantity -= called_shares
        shares.realized_profit += (call.strike - shares.assignment_strike) * called_shares
        if shares.remaining_quantity == 0:
            shares.state = "closed"
        self._refresh_round_for_call(call)
        self._post_profit(
            f"wheel-call:{call.id}", call.realized_profit, assigned_on
        )
        self.session.commit()
        return call

    def void_put(self, put_id: int, reason: str) -> WheelPutLot:
        record = self._put(put_id)
        descendants = self.session.scalar(
            select(func.count(WheelShareLot.id)).where(
                WheelShareLot.put_lot_id == put_id,
                WheelShareLot.state != "voided",
            )
        )
        if descendants:
            raise ValueError("该 Put 存在后续记录，必须撤销整条关联链")
        self._void(record, reason)
        self._reverse_profit(f"wheel-put:{record.id}", reason)
        self._refresh_round(record.round_id)
        self.session.commit()
        return record

    def void_chain(self, put_id: int, reason: str) -> dict[str, int]:
        put = self._put(put_id)
        shares = list(
            self.session.scalars(
                select(WheelShareLot).where(
                    WheelShareLot.put_lot_id == put_id,
                    WheelShareLot.state != "voided",
                )
            )
        )
        share_ids = [row.id for row in shares]
        calls = (
            list(
                self.session.scalars(
                    select(WheelCallLot).where(
                        WheelCallLot.share_lot_id.in_(share_ids),
                        WheelCallLot.state != "voided",
                    )
                )
            )
            if share_ids
            else []
        )
        self._void(put, reason)
        for record in [*shares, *calls]:
            self._void(record, reason)
        self._reverse_profit(f"wheel-put:{put.id}", reason)
        for share in shares:
            self._reverse_profit(f"wheel-put-assignment:{share.id}", reason)
        for call in calls:
            self._reverse_profit(f"wheel-call:{call.id}", reason)
        self._refresh_round(put.round_id)
        self.session.commit()
        return {"puts": 1, "shares": len(shares), "calls": len(calls)}

    def round_number(self, round_id: int) -> int:
        return self._round(round_id).number

    def _post_profit(self, source_key: str, amount: Decimal, occurred_on: date) -> None:
        RealizedCashService(self.session).post(
            source_key, Bucket.WHEEL, amount, occurred_on
        )

    def _reverse_profit(self, source_key: str, reason: str) -> None:
        RealizedCashService(self.session).reverse(source_key, date.today(), reason)

    def has_exposure(self, symbol: str | None = None) -> bool:
        put_filters = [
            WheelPutLot.state == "open",
            WheelPutLot.open_quantity > 0,
        ]
        if symbol is not None:
            put_filters.append(WheelPutLot.symbol == symbol.upper())
        open_puts = self.session.scalar(
            select(func.count(WheelPutLot.id)).where(
                *put_filters,
            )
        )
        share_query = (
            select(func.count(WheelShareLot.id))
            .join(WheelPutLot, WheelShareLot.put_lot_id == WheelPutLot.id)
            .where(
                WheelShareLot.state == "held",
                WheelShareLot.remaining_quantity > 0,
            )
        )
        if symbol is not None:
            share_query = share_query.where(WheelPutLot.symbol == symbol.upper())
        held_shares = self.session.scalar(share_query)
        return bool(open_puts or held_shares)

    def overview(self) -> dict:
        option_balance_rows = {
            bucket: self.session.get(BucketBalance, bucket)
            for bucket in (Bucket.WHEEL.value, Bucket.LEAPS.value)
        }
        funded = sum(
            (
                row.amount
                for row in option_balance_rows.values()
                if row is not None
            ),
            ZERO,
        )
        portfolio = PortfolioStore(self.session).summary()
        target_row = portfolio.get("targets", {}).get("options", {})
        strategy_budget = target_row.get("amount", ZERO)
        target_fraction = target_row.get("fraction", ZERO)
        puts = list(self.session.scalars(select(WheelPutLot).where(WheelPutLot.state == "open")))
        shares = list(
            self.session.scalars(
                select(WheelShareLot).where(
                    WheelShareLot.state == "held",
                    WheelShareLot.remaining_quantity > 0,
                )
            )
        )
        put_collateral = sum((record.collateral for record in puts), ZERO)
        share_capital = sum((record.capital for record in shares), ZERO)
        capital_snapshot = CapitalAccountingService(self.session).snapshot()
        shared_exposure = capital_snapshot.options.committed
        status = budget_status(strategy_budget, shared_exposure)
        recommendations = recommend_batches(strategy_budget, shared_exposure)
        realized = sum(
            (
                row.realized_profit
                for model in (WheelPutLot, WheelCallLot)
                for row in self.session.scalars(
                    select(model).where(model.state != "voided")
                )
            ),
            ZERO,
        )
        rounds = list(
            self.session.scalars(select(WheelRound).order_by(WheelRound.number.asc()))
        )
        funding_gap = max(strategy_budget - funded, ZERO).quantize(Decimal("0.01"))
        funding_excess = max(funded - strategy_budget, ZERO).quantize(Decimal("0.01"))
        unfunded_exposure = max(shared_exposure - funded, ZERO).quantize(
            Decimal("0.01")
        )
        return {
            "capital": {
                "assigned": capital_snapshot.options.assigned,
                "put_collateral": put_collateral.quantize(Decimal("0.01")),
                "share_capital": share_capital.quantize(Decimal("0.01")),
                "strategy_committed": capital_snapshot.wheel.committed,
                "committed": capital_snapshot.options.committed,
                "available": capital_snapshot.options.available,
                "cash_occupancy": capital_snapshot.options.cash_occupancy,
                "cash_available": capital_snapshot.cash.available,
                "margin_shortfall": capital_snapshot.cash.margin_shortfall,
            },
            "budget": {
                **asdict(status),
                "target_fraction": target_fraction,
                "funded": funded.quantize(Decimal("0.01")),
                "funding_gap": funding_gap,
                "funding_excess": funding_excess,
                "unfunded_exposure": unfunded_exposure,
            },
            "recommendations": asdict(recommendations),
            "realized_profit": realized.quantize(Decimal("0.01")),
            "rounds": [self._round_payload(record) for record in rounds],
        }

    def _refresh_round(self, round_id: int) -> None:
        round_record = self._round(round_id)
        puts = list(
            self.session.scalars(
                select(WheelPutLot).where(WheelPutLot.round_id == round_id)
            )
        )
        calls = list(
            self.session.scalars(
                select(WheelCallLot)
                .join(WheelShareLot, WheelCallLot.share_lot_id == WheelShareLot.id)
                .join(WheelPutLot, WheelShareLot.put_lot_id == WheelPutLot.id)
                .where(WheelPutLot.round_id == round_id)
            )
        )
        round_record.realized_profit = sum(
            (row.realized_profit for row in [*puts, *calls] if row.state != "voided"),
            ZERO,
        )
        active_put = any(row.state == "open" and row.open_quantity > 0 for row in puts)
        active_share = bool(
            self.session.scalar(
                select(func.count(WheelShareLot.id))
                .join(WheelPutLot, WheelShareLot.put_lot_id == WheelPutLot.id)
                .where(
                    WheelPutLot.round_id == round_id,
                    WheelShareLot.state == "held",
                    WheelShareLot.remaining_quantity > 0,
                )
            )
        )
        if puts and not active_put and not active_share:
            round_record.status = "completed"
            close_dates = [row.closed_on or row.trade_date for row in puts]
            close_dates.extend(row.closed_on or row.trade_date for row in calls)
            round_record.closed_on = max(close_dates)
        else:
            round_record.status = "active"
            round_record.closed_on = None

    def _refresh_round_for_call(self, call: WheelCallLot) -> None:
        share = self._share(call.share_lot_id)
        put = self._put(share.put_lot_id)
        self._refresh_round(put.round_id)

    def _round_payload(self, record: WheelRound) -> dict:
        puts = list(
            self.session.scalars(
                select(WheelPutLot)
                .where(WheelPutLot.round_id == record.id)
                .order_by(WheelPutLot.batch_number.asc(), WheelPutLot.id.asc())
            )
        )
        calls = [
            call
            for put in puts
            for share in self.session.scalars(
                select(WheelShareLot).where(WheelShareLot.put_lot_id == put.id)
            )
            for call in self.session.scalars(
                select(WheelCallLot).where(WheelCallLot.share_lot_id == share.id)
            )
            if call.state != "voided"
        ]
        realized = sum(
            (row.realized_profit for row in [*puts, *calls] if row.state != "voided"),
            ZERO,
        ).quantize(Decimal("0.01"))
        return {
            "id": record.id,
            "number": record.number,
            "opened_on": record.opened_on,
            "closed_on": record.closed_on,
            "status": record.status,
            "realized_profit": realized,
            "voided_at": record.voided_at,
            "void_reason": record.void_reason,
            "puts": [self._put_payload(put) for put in puts],
        }

    def _put_payload(self, record: WheelPutLot) -> dict:
        shares = list(
            self.session.scalars(
                select(WheelShareLot)
                .where(WheelShareLot.put_lot_id == record.id)
                .order_by(WheelShareLot.id.asc())
            )
        )
        opening_dte = (record.expiration - record.trade_date).days
        opening_annualized = annualized_return(
            record.premium,
            record.strike,
            opening_dte,
        )
        early_close_days: int | None = None
        early_close_annualized: Decimal | None = None
        early_close_return_kind: str | None = None
        if (
            record.state == "open"
            and record.captured_fraction is not None
            and record.quote_as_of is not None
        ):
            early_close_days = (record.quote_as_of.date() - record.trade_date).days
            early_close_annualized = annualized_return(
                record.premium * record.captured_fraction,
                record.strike,
                early_close_days,
            )
            early_close_return_kind = "estimated"
        elif (
            record.state in {"closed", "rolled"}
            and record.closed_on is not None
            and record.close_premium is not None
        ):
            early_close_days = (record.closed_on - record.trade_date).days
            closed_contracts = record.quantity - record.assigned_contracts
            early_close_annualized = annualized_return(
                (record.premium - record.close_premium) * HUNDRED * closed_contracts,
                record.strike * HUNDRED * closed_contracts,
                early_close_days,
            )
            early_close_return_kind = "actual"
        rolled_from = (
            self.session.get(WheelPutLot, record.rolled_from_put_id)
            if record.rolled_from_put_id is not None
            else None
        )
        rolled_to = self.session.scalar(
            select(WheelPutLot).where(WheelPutLot.rolled_from_put_id == record.id)
        )
        roll_count = 0
        ancestor = rolled_from
        while ancestor is not None:
            roll_count += 1
            ancestor = (
                self.session.get(WheelPutLot, ancestor.rolled_from_put_id)
                if ancestor.rolled_from_put_id is not None
                else None
            )
        return {
            "id": record.id,
            "round_id": record.round_id,
            "symbol": record.symbol,
            "batch_number": record.batch_number,
            "trade_date": record.trade_date,
            "expiration": record.expiration,
            "strike": record.strike,
            "premium": record.premium,
            "quantity": record.quantity,
            "open_quantity": record.open_quantity,
            "assigned_contracts": record.assigned_contracts,
            "entry_tqqq_price": record.entry_tqqq_price,
            "entry_underlying_price": record.entry_tqqq_price,
            "earnings_confirmed": record.earnings_confirmed,
            "state": record.state,
            "closed_on": record.closed_on,
            "close_premium": record.close_premium,
            "realized_profit": record.realized_profit,
            "collateral": record.collateral if record.state == "open" else ZERO,
            "opening_dte": opening_dte,
            "opening_annualized_return": opening_annualized,
            "early_close_days": early_close_days,
            "early_close_annualized_return": early_close_annualized,
            "early_close_return_kind": early_close_return_kind,
            "quote_source": record.quote_source,
            "quote_bid": record.quote_bid,
            "quote_ask": record.quote_ask,
            "quote_last": record.quote_last,
            "quote_iv": record.quote_iv,
            "quote_as_of": record.quote_as_of,
            "theoretical_low": record.theoretical_low,
            "theoretical_base": record.theoretical_base,
            "theoretical_high": record.theoretical_high,
            "captured_fraction": record.captured_fraction,
            "early_close_code": record.early_close_code,
            "early_close_message": record.early_close_message,
            "voided_at": record.voided_at,
            "void_reason": record.void_reason,
            "roll_count": roll_count,
            "rolled_from": self._roll_payload(rolled_from, record) if rolled_from else None,
            "rolled_to": self._roll_payload(record, rolled_to) if rolled_to else None,
            "share_lots": [self._share_payload(share) for share in shares],
        }

    @staticmethod
    def _roll_payload(previous: WheelPutLot, current: WheelPutLot) -> dict:
        contracts = min(previous.quantity, current.quantity)
        net_credit = (current.premium - (previous.close_premium or ZERO)) * HUNDRED * contracts
        return {
            "from_put_id": previous.id,
            "to_put_id": current.id,
            "rolled_on": current.trade_date,
            "from_expiration": previous.expiration,
            "from_strike": previous.strike,
            "to_expiration": current.expiration,
            "to_strike": current.strike,
            "buyback_premium": previous.close_premium,
            "new_premium": current.premium,
            "quantity": contracts,
            "net_credit": net_credit.quantize(Decimal("0.01")),
            "previous_realized_profit": previous.realized_profit,
        }

    def _share_payload(self, record: WheelShareLot) -> dict:
        calls = list(
            self.session.scalars(
                select(WheelCallLot)
                .where(WheelCallLot.share_lot_id == record.id)
                .order_by(WheelCallLot.id.asc())
            )
        )
        covered = sum((call.quantity for call in calls if call.state == "open"), 0)
        return {
            "id": record.id,
            "put_lot_id": record.put_lot_id,
            "assigned_on": record.assigned_on,
            "assignment_strike": record.assignment_strike,
            "original_quantity": record.original_quantity,
            "remaining_quantity": record.remaining_quantity,
            "state": record.state,
            "realized_profit": record.realized_profit,
            "capital": record.capital if record.state == "held" else ZERO,
            "covered_contracts": covered,
            "available_call_contracts": max(record.remaining_quantity // 100 - covered, 0),
            "voided_at": record.voided_at,
            "void_reason": record.void_reason,
            "calls": [self._call_payload(call) for call in calls],
        }

    @staticmethod
    def _call_payload(record: WheelCallLot) -> dict:
        return {
            "id": record.id,
            "share_lot_id": record.share_lot_id,
            "trade_date": record.trade_date,
            "expiration": record.expiration,
            "strike": record.strike,
            "premium": record.premium,
            "quantity": record.quantity,
            "state": record.state,
            "closed_on": record.closed_on,
            "close_premium": record.close_premium,
            "realized_profit": record.realized_profit,
            "quote_source": record.quote_source,
            "quote_bid": record.quote_bid,
            "quote_ask": record.quote_ask,
            "quote_last": record.quote_last,
            "quote_iv": record.quote_iv,
            "quote_as_of": record.quote_as_of,
            "voided_at": record.voided_at,
            "void_reason": record.void_reason,
        }

    def _round(self, round_id: int) -> WheelRound:
        record = self.session.get(WheelRound, round_id)
        if record is None:
            raise ValueError("找不到车轮轮次")
        return record

    def _put(self, put_id: int) -> WheelPutLot:
        record = self.session.get(WheelPutLot, put_id)
        if record is None:
            raise ValueError("找不到 Sell Put 记录")
        return record

    def _require_put_open(self, put_id: int) -> WheelPutLot:
        record = self._put(put_id)
        if record.state != "open" or record.open_quantity <= 0:
            raise ValueError("该 Sell Put 当前不能执行此操作")
        return record

    def _share(self, share_lot_id: int) -> WheelShareLot:
        record = self.session.get(WheelShareLot, share_lot_id)
        if record is None:
            raise ValueError("找不到接股记录")
        return record

    def _call(self, call_id: int) -> WheelCallLot:
        record = self.session.get(WheelCallLot, call_id)
        if record is None:
            raise ValueError("找不到 Covered Call 记录")
        return record

    def _require_call_open(self, call_id: int) -> WheelCallLot:
        record = self._call(call_id)
        if record.state != "open":
            raise ValueError("该 Covered Call 当前不能执行此操作")
        return record

    @staticmethod
    def _validate_option(
        trade_date: date,
        expiration: date,
        strike: Decimal,
        premium: Decimal,
        quantity: int,
    ) -> None:
        if expiration <= trade_date:
            raise ValueError("到期日必须晚于交易日")
        if strike <= ZERO or premium <= ZERO or quantity <= 0:
            raise ValueError("期权成交参数无效")

    @staticmethod
    def _void(record, reason: str) -> None:
        if not reason.strip():
            raise ValueError("撤销原因不能为空")
        record.state = "voided"
        record.void_reason = reason.strip()
        record.voided_at = datetime.now()
