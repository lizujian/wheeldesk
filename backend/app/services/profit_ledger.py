from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import BucketBalance, LedgerEvent, ProfitLedgerEntry, WheelCallLot, WheelPutLot, WheelShareLot
from app.domain.models import Bucket
from app.services.realized_cash import RealizedCashService
from app.services.capital_accounting import CapitalAccountingService

ZERO = Decimal("0")
CENT = Decimal("0.01")


class ProfitLedgerService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record_realized(
        self,
        source: str,
        occurred_on: date,
        amount: Decimal,
        note: str = "",
    ) -> dict:
        if source not in {"leaps", "other"} or amount == ZERO:
            raise ValueError("已实现盈亏记录无效")
        record = ProfitLedgerEntry(
                entry_type="realized",
                source=source,
                amount=amount,
                occurred_on=occurred_on,
                note=note,
                details={},
        )
        self.session.add(record)
        self.session.flush()
        source_key = f"manual-profit:{record.id}"
        record.details = {"source_key": source_key}
        RealizedCashService(self.session).post(
            source_key,
            Bucket.LEAPS if source == "leaps" else Bucket.CASH,
            amount,
            occurred_on,
        )
        self.session.commit()
        return self.snapshot()

    def record_allocation(
        self,
        occurred_on: date,
        amount: Decimal,
        allocations: dict,
        note: str = "",
    ) -> dict:
        available = self._summary()["available"]
        if amount > available:
            raise ValueError(f"确认金额超过当前可分配收益 {available.quantize(CENT)}")
        cash = self.session.get(BucketBalance, Bucket.CASH.value)
        transfer_amount = sum(
            (
                value
                for bucket, value in allocations.items()
                if getattr(bucket, "value", str(bucket)) != Bucket.CASH.value
            ),
            ZERO,
        )
        available_cash = CapitalAccountingService(self.session).snapshot().cash.available
        if transfer_amount > available_cash:
            raise ValueError(f"可用现金不足，当前仅可使用 {available_cash.quantize(CENT)}")
        if cash is None or cash.amount < transfer_amount:
            raise ValueError("现金储备不足，无法确认本次分配")
        details = {
            "allocations": {
                getattr(bucket, "value", str(bucket)): float(value)
                for bucket, value in allocations.items()
                if value != ZERO
            }
        }
        self.session.add(
            ProfitLedgerEntry(
                entry_type="allocation",
                source="allocation",
                amount=amount,
                occurred_on=occurred_on,
                note=note,
                details=details,
            )
        )
        for bucket, value in allocations.items():
            name = getattr(bucket, "value", str(bucket))
            if value == ZERO or name == Bucket.CASH.value:
                continue
            target = self.session.get(BucketBalance, name)
            if target is None:
                target = BucketBalance(bucket=name, amount=ZERO)
                self.session.add(target)
            cash.amount -= value
            target.amount += value
            self.session.add_all(
                [
                    LedgerEvent(
                        event_type="profit_allocation",
                        bucket=Bucket.CASH.value,
                        amount=-value,
                        occurred_on=occurred_on,
                        details={"target": name, "note": note},
                    ),
                    LedgerEvent(
                        event_type="profit_allocation",
                        bucket=name,
                        amount=value,
                        occurred_on=occurred_on,
                        details={"source": Bucket.CASH.value, "note": note},
                    ),
                ]
            )
        self.session.commit()
        return self.snapshot()

    def delete_manual(self, entry_id: str) -> dict:
        prefix = "manual:"
        if not entry_id.startswith(prefix):
            raise ValueError("自动流水必须从来源交易中更正")
        try:
            record_id = int(entry_id.removeprefix(prefix))
        except ValueError as error:
            raise ValueError("收益流水编号无效") from error
        record = self.session.get(ProfitLedgerEntry, record_id)
        if record is None:
            raise ValueError("找不到收益流水")
        if record.details.get("automatic"):
            raise ValueError("自动流水必须从来源交易中更正")
        source_key = record.details.get("source_key")
        if source_key:
            RealizedCashService(self.session).reverse(
                source_key, date.today(), "删除误录收益流水"
            )
            self.session.commit()
            return self.snapshot()
        self.session.delete(record)
        self.session.commit()
        return self.snapshot()

    def snapshot(self) -> dict:
        summary = self._summary()
        entries = [*self._wheel_entries(), *self._manual_entries()]
        entries.sort(key=self._entry_sort_key, reverse=True)
        return {
            "summary": {key: value.quantize(CENT) for key, value in summary.items()},
            "entries": [
                {key: value for key, value in entry.items() if key != "raw_amount"}
                for entry in entries
            ],
        }

    def _summary(self) -> dict[str, Decimal]:
        wheel = sum((entry["raw_amount"] for entry in self._wheel_entries()), ZERO)
        manual = list(self.session.scalars(select(ProfitLedgerEntry)))
        leaps = sum(
            (row.amount for row in manual if row.entry_type == "realized" and row.source == "leaps"),
            ZERO,
        )
        other = sum(
            (row.amount for row in manual if row.entry_type == "realized" and row.source == "other"),
            ZERO,
        )
        allocated = sum((row.amount for row in manual if row.entry_type == "allocation"), ZERO)
        net = wheel + leaps + other
        return {
            "wheel_realized": wheel,
            "leaps_realized": leaps,
            "other_realized": other,
            "net_realized": net,
            "allocated": allocated,
            "available": max(net - allocated, ZERO),
        }

    def _wheel_entries(self) -> list[dict]:
        entries: list[dict] = []
        puts = self.session.scalars(
            select(WheelPutLot).where(
                WheelPutLot.state != "voided",
                WheelPutLot.realized_profit != ZERO,
            )
        )
        put_labels = {
            "closed": "平仓",
            "expired": "到期",
            "assigned": "行权",
            "open": "部分行权",
        }
        for record in puts:
            shares = list(
                self.session.scalars(
                    select(WheelShareLot).where(
                        WheelShareLot.put_lot_id == record.id,
                        WheelShareLot.state != "voided",
                    )
                )
            )
            assigned_profit = ZERO
            for share in shares:
                premium = record.premium * share.original_quantity
                assigned_profit += premium
                entries.append(
                    self._automatic_entry(
                        f"wheel-put-assignment:{share.id}",
                        share.assigned_on,
                        premium,
                        f"Sell Put #{record.id} 行权",
                    )
                )
            settlement_profit = record.realized_profit - assigned_profit
            if settlement_profit != ZERO:
                entries.append(
                    self._automatic_entry(
                        f"wheel-put:{record.id}",
                        record.closed_on or record.trade_date,
                        settlement_profit,
                        f"Sell Put #{record.id} {put_labels.get(record.state, '结算')}",
                    )
                )
        calls = self.session.scalars(
            select(WheelCallLot).where(
                WheelCallLot.state != "voided",
                WheelCallLot.realized_profit != ZERO,
            )
        )
        call_labels = {"closed": "平仓", "expired": "到期", "called_away": "股票被扣走"}
        for record in calls:
            entries.append(
                self._automatic_entry(
                    f"wheel-call:{record.id}",
                    record.closed_on or record.trade_date,
                    record.realized_profit,
                    f"Covered Call #{record.id} {call_labels.get(record.state, '结算')}",
                )
            )
        return entries

    def _manual_entries(self) -> list[dict]:
        records = self.session.scalars(
            select(ProfitLedgerEntry).order_by(
                ProfitLedgerEntry.occurred_on.desc(),
                ProfitLedgerEntry.id.desc(),
            )
        )
        return [
            {
                "id": (
                    f"automatic:{record.id}"
                    if record.details.get("automatic")
                    else f"manual:{record.id}"
                ),
                "entry_type": record.entry_type,
                "source": record.source,
                "occurred_on": record.occurred_on,
                "amount": -record.amount if record.entry_type == "allocation" else record.amount,
                "note": record.note,
                "automatic": bool(record.details.get("automatic")),
                "deletable": not bool(record.details.get("automatic")),
                "allocations": record.details.get("allocations", {}),
                "raw_amount": record.amount,
            }
            for record in records
        ]

    @staticmethod
    def _automatic_entry(entry_id: str, occurred_on: date, amount: Decimal, note: str) -> dict:
        return {
            "id": entry_id,
            "entry_type": "realized",
            "source": "wheel",
            "occurred_on": occurred_on,
            "amount": amount,
            "note": note,
            "automatic": True,
            "deletable": False,
            "allocations": {},
            "raw_amount": amount,
        }

    @staticmethod
    def _entry_sort_key(entry: dict) -> tuple:
        manual_id = int(entry["id"].split(":", 1)[1]) if entry["id"].startswith("manual:") else 0
        return entry["occurred_on"], entry["id"].startswith("manual:"), manual_id
