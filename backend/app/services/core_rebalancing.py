from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import BucketBalance, LedgerEvent, PositionRecord
from app.domain.models import Bucket
from app.services.portfolio_store import PortfolioStore

ZERO = Decimal("0")
CENT = Decimal("0.01")
SHARE = Decimal("0.0001")


class CoreRebalancingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def sell_fifo(
        self, sold_on: date, quantity: Decimal, price: Decimal, symbol: str = "BRK.B"
    ) -> dict:
        symbol = symbol.upper()
        if symbol not in {"BRK.B", "VOO"}:
            raise ValueError("核心仓再平衡标的只允许 BRK.B 或 VOO")
        quantity = quantity.quantize(SHARE)
        if quantity <= ZERO or price <= ZERO:
            raise ValueError("卖出股数和价格必须大于零")
        lots = list(
            self.session.scalars(
                select(PositionRecord)
                .where(
                    PositionRecord.bucket == Bucket.CORE.value,
                    PositionRecord.symbol == symbol,
                    PositionRecord.status == "open",
                    PositionRecord.quantity > ZERO,
                )
                .order_by(PositionRecord.opened_on.asc(), PositionRecord.id.asc())
            )
        )
        total_quantity = sum((lot.quantity for lot in lots), ZERO)
        if quantity > total_quantity:
            raise ValueError(f"卖出股数超过当前 {symbol} 持仓")

        remaining = quantity
        cost_basis = ZERO
        consumed: list[dict] = []
        for lot in lots:
            if remaining <= ZERO:
                break
            sold = min(lot.quantity, remaining)
            cost = lot.entry_price * sold * lot.multiplier
            proceeds = price * sold * lot.multiplier
            realized = proceeds - cost
            lot.quantity -= sold
            lot.current_price = price
            lot.realized_profit = (lot.realized_profit or ZERO) + realized
            if lot.quantity == ZERO:
                lot.status = "closed"
                lot.closed_on = sold_on
                lot.exit_price = price
                lot.exit_fees = ZERO
            cost_basis += cost
            remaining -= sold
            consumed.append(
                {
                    "position_id": lot.id,
                    "quantity": float(sold),
                    "cost_basis": float(cost),
                }
            )

        proceeds = price * quantity
        realized_profit = proceeds - cost_basis
        core = self._balance(Bucket.CORE)
        cash = self._balance(Bucket.CASH)
        if core.amount < cost_basis:
            raise ValueError("核心仓资金桶本金不足，无法结算再平衡卖出")
        core.amount -= cost_basis
        cash.amount += proceeds
        profile = PortfolioStore(self.session).profile()
        if profile is None:
            raise ValueError("请先初始化账户")
        profile.last_rebalanced_on = sold_on
        self.session.add(
            LedgerEvent(
                event_type="core_rebalance_sale",
                bucket=Bucket.CORE.value,
                amount=realized_profit,
                occurred_on=sold_on,
                details={
                    "symbol": symbol,
                    "quantity": float(quantity),
                    "price": float(price),
                    "cost_basis": float(cost_basis),
                    "proceeds": float(proceeds),
                    "lots": consumed,
                },
            )
        )
        self.session.commit()
        return {
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "cost_basis": cost_basis.quantize(CENT),
            "proceeds": proceeds.quantize(CENT),
            "realized_profit": realized_profit.quantize(CENT),
        }

    def _balance(self, bucket: Bucket) -> BucketBalance:
        row = self.session.get(BucketBalance, bucket.value)
        if row is None:
            row = BucketBalance(bucket=bucket.value, amount=ZERO)
            self.session.add(row)
        return row
