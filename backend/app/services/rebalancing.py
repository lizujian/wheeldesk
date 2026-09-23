from dataclasses import asdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import LedgerEvent, PositionRecord, WheelCallLot, WheelPutLot
from app.domain.allocation import allocation_targets
from app.domain.core import CORE_SYMBOLS
from app.domain.models import Bucket
from app.domain.rebalancing import evaluate_core_rebalance, review_schedule
from app.services.capital_accounting import CapitalAccountingService
from app.services.portfolio_store import PortfolioStore

ZERO = Decimal("0")
CENT = Decimal("0.01")
MATERIAL_GAP = Decimal("0.02")


class RebalancingService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def evaluate(self, as_of: date) -> dict:
        store = PortfolioStore(self.session)
        profile = store.profile()
        if profile is None:
            raise ValueError("请先初始化账户")

        balances = store.balances()
        capital = CapitalAccountingService(self.session).snapshot()
        positions = list(
            self.session.scalars(
                select(PositionRecord).where(PositionRecord.status == "open")
            )
        )
        core_positions = [row for row in positions if row.bucket == Bucket.CORE.value]
        leaps_positions = [row for row in positions if row.bucket == Bucket.LEAPS.value]
        core_unrealized = self._position_unrealized(core_positions)
        leaps_unrealized = self._position_unrealized(leaps_positions)
        wheel_unrealized = self._wheel_unrealized()

        values = {
            Bucket.CORE: capital.core.assigned + core_unrealized,
            Bucket.WHEEL: (
                capital.wheel.assigned
                + capital.options.cash_occupancy
                + wheel_unrealized
            ),
            Bucket.LEAPS: (
                capital.leaps.assigned
                + leaps_unrealized
            ),
            Bucket.CASH: (
                capital.cash.total
                - capital.options.cash_occupancy
            ),
        }
        total = sum(values.values(), ZERO).quantize(CENT)
        targets = allocation_targets(profile.age)
        economic_buckets = {}
        for bucket in (Bucket.CORE, Bucket.CASH):
            fraction = values[bucket] / total if total > ZERO else ZERO
            economic_buckets[bucket.value] = {
                "value": values[bucket].quantize(CENT),
                "fraction": fraction,
                "target_fraction": targets[bucket],
                "deviation": fraction - targets[bucket],
            }
        option_value = values[Bucket.WHEEL] + values[Bucket.LEAPS]
        option_target = targets[Bucket.WHEEL] + targets[Bucket.LEAPS]
        option_fraction = option_value / total if total > ZERO else ZERO
        economic_buckets["options"] = {
            "value": option_value.quantize(CENT),
            "fraction": option_fraction,
            "target_fraction": option_target,
            "deviation": option_fraction - option_target,
        }

        schedule = review_schedule(
            profile.opening_date, profile.last_rebalanced_on, as_of
        )
        core_symbol, core_price = self._core_sale_reference(
            core_positions,
        )
        core_decision = evaluate_core_rebalance(
            targets[Bucket.CORE],
            economic_buckets[Bucket.CORE.value]["fraction"],
            schedule.due,
            total,
            core_price,
            core_symbol,
        )
        recommendations = self._recommendations(
            total,
            values,
            targets,
            capital.cash.margin_shortfall,
            core_decision,
        )
        assigned_buckets = {
            bucket.value: balances[bucket]
            for bucket in (Bucket.CORE, Bucket.CASH, Bucket.WHEEL, Bucket.LEAPS)
        }
        return {
            "as_of": as_of,
            "schedule": {
                "last_rebalanced_on": profile.last_rebalanced_on,
                "next_review_on": schedule.next_review_on,
                "due": schedule.due,
            },
            "assigned": {
                "total": sum(assigned_buckets.values(), ZERO).quantize(CENT),
                "buckets": assigned_buckets,
            },
            "capital": capital.payload(),
            "economic": {
                "total": total,
                "buckets": economic_buckets,
                "unrealized": {
                    "core": core_unrealized.quantize(CENT),
                    "wheel": wheel_unrealized.quantize(CENT),
                    "leaps": leaps_unrealized.quantize(CENT),
                },
            },
            "core_price": core_price,
            "core_symbol": core_symbol,
            "core_decision": asdict(core_decision),
            "recommendations": recommendations,
        }

    def confirm_no_trade(self, confirmed_on: date) -> dict:
        store = PortfolioStore(self.session)
        profile = store.profile()
        if profile is None:
            raise ValueError("请先初始化账户")
        profile.last_rebalanced_on = confirmed_on
        self.session.add(
            LedgerEvent(
                event_type="rebalance_no_trade_confirmation",
                bucket=Bucket.CASH.value,
                amount=ZERO,
                occurred_on=confirmed_on,
                details={"result": "no_trade"},
            )
        )
        self.session.commit()
        return self.evaluate(confirmed_on)

    @staticmethod
    def _position_unrealized(positions: list[PositionRecord]) -> Decimal:
        return sum(
            (
                (row.current_price - row.entry_price)
                * row.quantity
                * row.multiplier
                for row in positions
            ),
            ZERO,
        )

    def _wheel_unrealized(self) -> Decimal:
        puts = self.session.scalars(
            select(WheelPutLot).where(
                WheelPutLot.state == "open", WheelPutLot.open_quantity > 0
            )
        )
        calls = self.session.scalars(
            select(WheelCallLot).where(WheelCallLot.state == "open")
        )
        put_profit = sum(
            (
                (row.premium - row.quote_ask) * 100 * row.open_quantity
                for row in puts
                if row.quote_ask is not None
            ),
            ZERO,
        )
        call_profit = sum(
            (
                (row.premium - row.quote_ask) * 100 * row.quantity
                for row in calls
                if row.quote_ask is not None
            ),
            ZERO,
        )
        return put_profit + call_profit

    @staticmethod
    def _core_sale_reference(
        positions: list[PositionRecord],
    ) -> tuple[str, Decimal]:
        values = {
            symbol: sum(
                (
                    row.current_price * row.quantity * row.multiplier
                    for row in positions
                    if row.symbol == symbol
                ),
                ZERO,
            )
            for symbol in CORE_SYMBOLS
        }
        costs = {
            symbol: sum(
                (
                    row.entry_price * row.quantity * row.multiplier
                    for row in positions
                    if row.symbol == symbol
                ),
                ZERO,
            )
            for symbol in CORE_SYMBOLS
        }
        symbol = max(
            CORE_SYMBOLS,
            key=lambda candidate: (
                (values[candidate] - costs[candidate]) / costs[candidate]
                if costs[candidate] > ZERO
                else Decimal("-1"),
                values[candidate],
            ),
            default="BRK.B",
        )
        matching = [row for row in positions if row.symbol == symbol and row.quantity > ZERO]
        quantity = sum((row.quantity * row.multiplier for row in matching), ZERO)
        if quantity <= ZERO:
            return symbol, ZERO
        market_value = sum(
            (row.current_price * row.quantity * row.multiplier for row in matching),
            ZERO,
        )
        return symbol, (market_value / quantity).quantize(Decimal("0.0001"))

    @staticmethod
    def _recommendations(
        total: Decimal,
        values: dict[Bucket, Decimal],
        targets: dict[Bucket, Decimal],
        margin_shortfall: Decimal,
        core_decision,
    ) -> list[dict]:
        recommendations: list[dict] = []

        def add(code: str, bucket: Bucket, amount: Decimal, message: str) -> None:
            recommendations.append(
                {
                    "priority": len(recommendations) + 1,
                    "code": code,
                    "bucket": bucket.value,
                    "amount": max(amount, ZERO).quantize(CENT),
                    "message": message,
                }
            )

        if margin_shortfall > ZERO:
            add(
                "eliminate_margin",
                Bucket.CASH,
                margin_shortfall,
                "优先补足策略占用现金，消除保证金缺口。",
            )
        cash_gap = max(total * targets[Bucket.CASH] - values[Bucket.CASH], ZERO)
        if cash_gap > ZERO:
            add(
                "restore_cash",
                Bucket.CASH,
                cash_gap,
                f"将现金经济权益恢复到总资产的 {(targets[Bucket.CASH] * 100).normalize()}%。",
            )
        option_target = targets[Bucket.WHEEL] + targets[Bucket.LEAPS]
        option_value = values[Bucket.WHEEL] + values[Bucket.LEAPS]
        option_gap = max(total * option_target - option_value, ZERO)
        if total > ZERO and option_gap / total >= MATERIAL_GAP:
            add(
                "replenish_options",
                Bucket.LEAPS,
                option_gap,
                "期权策略共享池低于目标至少 2 个百分点，建议在现金安全后补足 LEAPS/PMCC。",
            )
        if core_decision.actionable:
            add(
                "sell_core",
                Bucket.CORE,
                core_decision.sell_amount,
                "核心仓超过硬阈值，录入券商实际成交后按 FIFO 再平衡。",
            )
        return recommendations
