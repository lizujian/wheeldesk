from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db_models import (
    BrokerImportRecord,
    BucketBalance,
    LedgerEvent,
    PositionRecord,
    PortfolioProfile,
    UnmanagedPositionRecord,
    WheelCallLot,
    WheelPutLot,
    WheelRound,
    WheelShareLot,
)
from app.domain.models import Bucket
from app.domain.core import CORE_PUT_SYMBOLS, CORE_SYMBOLS
from app.domain.leaps import LEAPS_CALL_WHEEL_CATEGORY
from app.db_models import CoreTradeRecord
from app.domain.trillion_club import is_club_symbol, is_wheel_club_symbol
from app.services.portfolio_store import PortfolioStore
from app.services.realized_cash import RealizedCashService
from app.services.other_holdings import OtherHoldingService
from app.services.wheel_portfolio import WheelPortfolioService

ZERO = Decimal("0")
HUNDRED = Decimal("100")
PRICE_QUANTUM = Decimal("0.0001")

SECTION_ALIASES = {
    "未平仓持仓": "open_positions",
    "存款和取款": "deposits",
    "交易": "trades",
    "净资产值变更": "nav_change",
}

HEADER_ALIASES = {
    "域名称": "Field Name",
    "域值": "Field Value",
    "资产分类": "Asset Category",
    "货币": "Currency",
    "开盘": "Open Date",
    "数量": "Quantity",
    "合约乘数": "Mult",
    "成本价格": "Cost Price",
    "成本基础": "Cost Basis",
    "收盘价格": "Close Price",
    "价值": "Value",
    "未实现的损益": "Unrealized P/L",
    "日期/时间": "Date/Time",
    "交易价格": "T. Price",
    "收益": "Proceeds",
    "佣金/税": "Comm/Fee",
    "基础": "Basis",
    "已实现的损益": "Realized P/L",
    "按市值计算的损益": "MTM P/L",
    "结算日期": "Settle Date",
    "描述": "Description",
    "金额": "Amount",
}

CHINESE_MONTHS = {
    "一月": "January",
    "二月": "February",
    "三月": "March",
    "四月": "April",
    "五月": "May",
    "六月": "June",
    "七月": "July",
    "八月": "August",
    "九月": "September",
    "十月": "October",
    "十一月": "November",
    "十二月": "December",
}


@dataclass(frozen=True)
class StatementRow:
    section: str
    row_index: int
    values: dict[str, str]
    fingerprint: str
    legacy_fingerprint: str
    report_as_of: date | None


@dataclass(frozen=True)
class Contract:
    symbol: str
    asset_type: str
    quantity: Decimal
    cost_price: Decimal
    close_price: Decimal
    expiration: date | None = None
    strike: Decimal | None = None
    option_type: str | None = None

    @property
    def key(self) -> tuple[str, str, date | None, Decimal | None, str | None]:
        return (
            self.symbol,
            self.asset_type,
            self.expiration,
            self.strike,
            self.option_type,
        )


@dataclass(frozen=True)
class PutRoll:
    closing_row: StatementRow
    closing_contract: Contract
    opening_row: StatementRow
    opening_contract: Contract
    traded_at: datetime


@dataclass(frozen=True)
class PositionRoll:
    closing_row: StatementRow
    closing_contract: Contract
    opening_row: StatementRow
    opening_contract: Contract
    traded_at: datetime


class IbkrImportService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def preview(self, filename: str, content: str) -> dict[str, Any]:
        rows = parse_activity_statement(content)
        if not rows:
            raise ValueError("未识别到 IBKR Activity Statement CSV 数据行")

        trade_dates = self._trade_dates(rows)
        put_rolls = self._put_rolls(rows)
        position_rolls = self._position_rolls(rows)
        roll_trade_fingerprints = {
            trade.fingerprint
            for roll in [*put_rolls.values(), *position_rolls.values()]
            for trade in (roll.closing_row, roll.opening_row)
        }
        opening_trades = self._opening_trades(rows)
        candidate_fingerprints = {
            value
            for row in rows
            for value in (row.fingerprint, row.legacy_fingerprint)
        }
        imported = set(
            self.session.scalars(
                select(BrokerImportRecord.fingerprint).where(
                    BrokerImportRecord.fingerprint.in_(candidate_fingerprints)
                )
            )
        )
        used_slots = self._used_leaps_slots()
        preview_rows: list[dict[str, Any]] = []
        recognized_sections: set[str] = set()

        for row in rows:
            section_key = _section_key(row.section)
            item: dict[str, Any] | None = None
            if section_key == "open_positions":
                recognized_sections.add("Open Positions")
                item = self._preview_position(
                    row,
                    trade_dates,
                    used_slots,
                    put_rolls,
                    position_rolls,
                    opening_trades,
                )
            elif section_key == "deposits":
                recognized_sections.add("Deposits & Withdrawals")
                item = self._preview_deposit(row)
            elif section_key == "trades":
                recognized_sections.add("Trades")
                item = self._preview_trade(
                    row,
                    roll_trade_fingerprints,
                    opening_trades,
                )
            if item is None:
                continue
            already_imported = (
                item["fingerprint"] in imported
                or row.fingerprint in imported
                or row.legacy_fingerprint in imported
            )
            if already_imported and section_key == "open_positions":
                if item["status"] == "matched":
                    item.update(
                        status="duplicate",
                        confidence="exact",
                        selected=False,
                        can_import=False,
                        action="skip",
                        message="该持仓快照已经导入且账务数据一致",
                    )
                elif item["can_import"]:
                    item["message"] = f"报表快照曾导入；检测到账务数据变化，{item['message']}"
            elif already_imported:
                item.update(
                    status="duplicate",
                    confidence="exact",
                    selected=False,
                    can_import=False,
                    action="skip",
                    message="该报表行已经导入",
                )
            preview_rows.append(item)

        if not preview_rows:
            raise ValueError("报表中没有可预览的持仓或入金数据")

        counts = {
            key: sum(1 for item in preview_rows if item["status"] == key)
            for key in ("ready", "matched", "review", "unsupported", "duplicate")
        }
        selected_count = sum(bool(item["selected"]) for item in preview_rows)
        return {
            "filename": filename,
            "report_as_of": max(
                (row.report_as_of for row in rows if row.report_as_of is not None),
                default=None,
            ),
            "recognized_sections": sorted(recognized_sections),
            "statement_rows": len(rows),
            "rows": preview_rows,
            "summary": {**counts, "selected": selected_count},
            "account_summary": _account_summary(content, rows),
        }

    def confirm(
        self,
        filename: str,
        content: str,
        selected_fingerprints: list[str],
        overrides: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        snapshot = self.preview(filename, content)
        selected = set(selected_fingerprints)
        available = {row["fingerprint"]: row for row in snapshot["rows"]}
        unknown = selected - set(available)
        if unknown:
            raise ValueError("导入选择已失效，请重新生成预览")

        default_selection = {
            row["fingerprint"] for row in snapshot["rows"] if row["selected"]
        }
        account_summary = (
            snapshot.get("account_summary")
            if default_selection <= selected
            else None
        )
        first_import = not bool(
            self.session.scalar(select(func.count(BrokerImportRecord.id)))
        )
        if account_summary and first_import:
            self._prepare_initial_account_summary(account_summary)

        results: list[dict[str, Any]] = []
        for fingerprint in selected_fingerprints:
            item = available[fingerprint]
            if not item["can_import"] or item["status"] in {"duplicate", "unsupported"}:
                raise ValueError(f"{item['instrument']} 当前不能直接导入")
            entity_type, entity_id = self._apply(
                item,
                overrides.get(fingerprint, {}),
                deposit_affects_balance=account_summary is None,
            )
            record = self.session.scalar(
                select(BrokerImportRecord).where(
                    BrokerImportRecord.fingerprint == fingerprint
                )
            )
            if record is None:
                record = BrokerImportRecord(fingerprint=fingerprint)
                self.session.add(record)
            record.filename = filename
            record.section = item["section"]
            record.row_index = item["row_index"]
            record.action = item["action"]
            record.entity_type = entity_type
            record.entity_id = entity_id
            record.raw = item["source"]
            self.session.commit()
            results.append(
                {
                    "fingerprint": fingerprint,
                    "instrument": item["instrument"],
                    "action": item["action"],
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                }
            )
        if default_selection <= selected:
            self._record_core_trades(parse_activity_statement(content))
        if account_summary:
            self._reconcile_account_summary(account_summary, filename)
        return {"imported": len(results), "results": results}

    def _record_core_trades(self, rows: list[StatementRow]) -> None:
        quantities = {symbol: ZERO for symbol in CORE_SYMBOLS}
        has_snapshot = any(_section_key(row.section) == "open_positions" for row in rows)
        trades = []
        occurrences: dict[str, int] = {}
        for row in rows:
            contract = _contract(row.values)
            if contract is None or contract.asset_type != "equity" or contract.symbol not in CORE_SYMBOLS:
                continue
            if _section_key(row.section) == "open_positions":
                quantities[contract.symbol] += contract.quantity
            elif _section_key(row.section) == "trades":
                if _value(row.values, "DataDiscriminator").lower() not in {"", "order"}:
                    continue
                traded_at = _parse_datetime(_value(row.values, "Date/Time", "Trade Date", "Date"))
                if traded_at is None or contract.quantity == ZERO or contract.cost_price <= ZERO:
                    continue
                key = json.dumps([
                    contract.symbol, traded_at.isoformat(),
                    str(contract.quantity.normalize()), str(contract.cost_price.normalize()),
                    _value(row.values, "Currency"),
                ])
                occurrences[key] = occurrences.get(key, 0) + 1
                fingerprint = hashlib.sha256(f"{key}:{occurrences[key]}".encode()).hexdigest()
                trades.append((traded_at, row.row_index, fingerprint, contract))
        ending_quantities = quantities.copy()
        new_sales = set()
        # Reverse the report's executions from its ending stock snapshot.
        for traded_at, _, fingerprint, contract in sorted(trades, reverse=True, key=lambda value: value[:2]):
            quantities[contract.symbol] -= contract.quantity
            pre = {symbol: str(value) for symbol, value in quantities.items()} if has_snapshot and all(value >= ZERO for value in quantities.values()) else None
            record = self.session.scalar(select(CoreTradeRecord).where(CoreTradeRecord.fingerprint == fingerprint))
            if record is None:
                if contract.quantity < ZERO:
                    new_sales.add(fingerprint)
                self.session.add(CoreTradeRecord(
                    fingerprint=fingerprint, symbol=contract.symbol, traded_at=traded_at,
                    quantity=contract.quantity, price=contract.cost_price, pre_quantities=pre,
                ))
            elif record.pre_quantities is None and pre is not None:
                record.pre_quantities = pre
        if has_snapshot:
            from app.services.core_rebalancing import CoreRebalancingService

            for symbol, ending_quantity in ending_quantities.items():
                sales = [(stamp, contract) for stamp, _, fingerprint, contract in trades
                         if contract.symbol == symbol and fingerprint in new_sales]
                if ending_quantity != ZERO or not sales:
                    continue
                held = list(self.session.scalars(select(PositionRecord).where(
                    PositionRecord.bucket == Bucket.CORE.value, PositionRecord.symbol == symbol,
                    PositionRecord.asset_type == "equity", PositionRecord.status == "open",
                )))
                quantity = sum((record.quantity for record in held), ZERO)
                sold_quantity = sum((abs(contract.quantity) for _, contract in sales), ZERO)
                sold_on = max(stamp.date() for stamp, _ in sales)
                if quantity <= ZERO or sold_quantity < quantity or any(
                    record.opened_on > sold_on or (record.quote_as_of and record.quote_as_of.date() > sold_on)
                    for record in held
                ):
                    continue
                price = sum((abs(contract.quantity) * contract.cost_price for _, contract in sales), ZERO) / sold_quantity
                CoreRebalancingService(self.session).sell_fifo(sold_on, quantity, price, symbol)
        self.session.commit()

    def import_all(self, filename: str, content: str) -> dict[str, Any]:
        snapshot = self.preview(filename, content)
        selected = [
            row["fingerprint"]
            for row in snapshot["rows"]
            if row["selected"] and row["can_import"]
        ]
        confirmed = (
            self.confirm(filename, content, selected, {})
            if selected
            else {"imported": 0, "results": []}
        )
        notices = [
            {
                "instrument": row["instrument"],
                "status": row["status"],
                "message": row["message"],
            }
            for row in snapshot["rows"]
            if row["status"] in {"review", "unsupported"}
        ]
        unchanged = snapshot["summary"]["matched"] + snapshot["summary"]["duplicate"]
        return {
            "filename": filename,
            "report_as_of": snapshot["report_as_of"],
            "statement_rows": snapshot["statement_rows"],
            "imported": confirmed["imported"],
            "unchanged": unchanged,
            "needs_attention": len(notices),
            "results": confirmed["results"],
            "notices": notices,
        }

    def _prepare_initial_account_summary(self, summary: dict[str, Any]) -> None:
        profile = self.session.get(PortfolioProfile, 1)
        if profile is None:
            raise ValueError("请先初始化账户")
        starting_value = summary.get("starting_value")
        period_start = summary.get("period_start")
        if starting_value is not None and Decimal(str(starting_value)) > ZERO:
            profile.opening_equity = Decimal(str(starting_value))
        if period_start:
            profile.opening_date = date.fromisoformat(str(period_start))
        self.session.execute(
            delete(LedgerEvent).where(LedgerEvent.event_type == "deposit")
        )
        self.session.flush()

    def _reconcile_account_summary(
        self, summary: dict[str, Any], filename: str
    ) -> None:
        ending_value = Decimal(str(summary["ending_value"]))
        balances = list(self.session.scalars(select(BucketBalance)))
        current_total = sum((row.amount for row in balances), ZERO)
        adjustment = (ending_value - current_total).quantize(Decimal("0.01"))
        if adjustment == ZERO:
            return
        cash = self.session.get(BucketBalance, Bucket.CASH.value)
        if cash is None:
            cash = BucketBalance(bucket=Bucket.CASH.value, amount=ZERO)
            self.session.add(cash)
        cash.amount += adjustment
        occurred_on = date.fromisoformat(str(summary["period_end"]))
        self.session.add(
            LedgerEvent(
                event_type="broker_nav_reconciliation",
                bucket=Bucket.CASH.value,
                amount=adjustment,
                occurred_on=occurred_on,
                details={
                    "filename": filename,
                    "source": "IBKR",
                    "previous_total": float(current_total),
                    "ending_value": float(ending_value),
                },
            )
        )
        self.session.commit()

    def history(self) -> list[dict[str, Any]]:
        records = list(
            self.session.scalars(
                select(BrokerImportRecord)
                .order_by(BrokerImportRecord.created_at.desc(), BrokerImportRecord.id.desc())
                .limit(100)
            )
        )
        return [
            {
                "id": row.id,
                "filename": row.filename,
                "section": row.section,
                "row_index": row.row_index,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "instrument": row.raw.get("Symbol") or row.raw.get("Description") or "-",
                "created_at": row.created_at,
            }
            for row in records
        ]

    def _preview_deposit(self, row: StatementRow) -> dict[str, Any] | None:
        amount = _decimal(_value(row.values, "Amount", "Net Amount", "金额"))
        if amount <= ZERO:
            return self._item(
                row,
                instrument=_value(row.values, "Description", "Activity Description") or "资金变动",
                action="skip",
                status="unsupported",
                confidence="low",
                selected=False,
                can_import=False,
                message="目前仅自动导入正数外部入金",
                details={"amount": float(amount)},
            )
        occurred_on = _parse_date(
            _value(row.values, "Settle Date", "Date", "Activity Date")
        )
        if occurred_on is None:
            return self._item(
                row,
                instrument="外部入金",
                action="deposit",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="无法识别入金日期",
                details={"amount": float(amount)},
            )
        description = _value(row.values, "Description", "Activity Description") or "IBKR 报表入金"
        return self._item(
            row,
            instrument=description,
            action="deposit",
            status="ready",
            confidence="exact",
            selected=True,
            can_import=True,
            message=f"新增现金 ${amount:,.2f}",
            details={
                "amount": float(amount),
                "occurred_on": occurred_on.isoformat(),
                "note": description,
            },
        )

    def _preview_position(
        self,
        row: StatementRow,
        trade_dates: dict[tuple[Any, ...], date],
        used_slots: dict[str, set[int]],
        put_rolls: dict[tuple[Any, ...], PutRoll],
        position_rolls: dict[tuple[Any, ...], PositionRoll],
        opening_trades: dict[
            tuple[Any, ...], list[tuple[StatementRow, Contract, datetime]]
        ],
    ) -> dict[str, Any]:
        contract = _contract(row.values)
        if contract is None:
            return self._item(
                row,
                instrument=_value(row.values, "Symbol") or "未知持仓",
                action="skip",
                status="unsupported",
                confidence="low",
                selected=False,
                can_import=False,
                message="无法识别资产类型或期权合约",
                details={},
            )
        matching_entries = [
            trade_contract
            for _, trade_contract, _ in opening_trades.get(contract.key, [])
            if trade_contract.quantity == contract.quantity
        ]
        if len(matching_entries) == 1:
            # Open Positions reports commission-adjusted cost basis. Strategy
            # accounting intentionally uses the fill price from Trades.
            contract = replace(contract, cost_price=matching_entries[0].cost_price)
        opened_on = trade_dates.get(contract.key)
        date_confidence = "exact" if opened_on is not None else "estimated"
        opened_on = opened_on or row.report_as_of or date.today()
        if contract.asset_type == "equity" and contract.quantity > ZERO:
            return self._preview_equity(row, contract, opened_on, date_confidence, used_slots)
        if contract.asset_type == "option" and contract.option_type == "call":
            if contract.quantity > ZERO:
                position_roll = position_rolls.get(contract.key)
                if position_roll is not None:
                    return self._preview_position_roll(
                        row,
                        contract,
                        position_roll,
                    )
                return self._preview_leaps(row, contract, opened_on, date_confidence, used_slots)
            leaps_call = self._preview_leaps_call(row, contract, opened_on, date_confidence)
            if leaps_call is not None:
                return leaps_call
            return self._preview_covered_call(row, contract, opened_on, date_confidence)
        if (
            contract.asset_type == "option"
            and contract.option_type == "put"
            and contract.quantity < ZERO
        ):
            put_roll = put_rolls.get(contract.key)
            if put_roll is not None:
                return self._preview_wheel_roll(row, contract, put_roll)
            return self._preview_wheel_put(row, contract, opened_on, date_confidence)
        if contract.asset_type == "option" and contract.option_type == "put":
            return self._preview_unmanaged(row, contract, opened_on, date_confidence)
        return self._item(
            row,
            instrument=_instrument_label(contract),
            action="skip",
            status="unsupported",
            confidence="low",
            selected=False,
            can_import=False,
            message="该方向暂不属于核心仓、LEAPS 或车轮持仓",
            details=_contract_details(contract, opened_on),
        )

    def _preview_equity(
        self,
        row: StatementRow,
        contract: Contract,
        opened_on: date,
        confidence: str,
        used_slots: dict[str, set[int]],
    ) -> dict[str, Any]:
        symbol = contract.symbol
        if symbol in {"BRK.B", "VOO", "QLD"}:
            bucket = Bucket.LEAPS if symbol == "QLD" else Bucket.CORE
            existing_rows = list(
                self.session.scalars(
                    select(PositionRecord).where(
                        PositionRecord.status == "open",
                        PositionRecord.bucket == bucket.value,
                        PositionRecord.symbol == symbol,
                        PositionRecord.asset_type == "equity",
                    )
                )
            )
            if len(existing_rows) > 1:
                exact = _position_group_matches(existing_rows, contract)
                return self._item(
                    row,
                    instrument=symbol,
                    action="skip",
                    status="matched" if exact else "review",
                    confidence="exact" if exact else "low",
                    selected=False,
                    can_import=False,
                    message=(
                        f"已按 {len(existing_rows)} 个系统批次合计匹配"
                        if exact
                        else f"IBKR 聚合持仓对应 {len(existing_rows)} 个系统批次，需要人工核对"
                    ),
                    details=_contract_details(contract, opened_on),
                )
            existing = existing_rows[0] if existing_rows else None
            details = _contract_details(contract, opened_on)
            details["bucket"] = bucket.value
            if symbol == "QLD":
                tranche = existing.tranche if existing else _claim_slot(used_slots, "QQQ", 5)
                if tranche is None:
                    return self._item(
                        row,
                        instrument=symbol,
                        action="skip",
                        status="review",
                        confidence="low",
                        selected=False,
                        can_import=False,
                        message="QQQ/QLD 五个槽位均已占用",
                        details=details,
                    )
                details["tranche"] = tranche
            action = "update_position" if existing else "create_position"
            details["position_id"] = existing.id if existing else None
            exact = existing is not None and _position_matches(existing, contract)
            return self._item(
                row,
                instrument=symbol,
                action="skip" if exact else action,
                status="matched" if exact else "ready",
                confidence=confidence,
                selected=not exact,
                can_import=not exact,
                message="系统持仓已经一致" if exact else ("更新现有持仓" if existing else "新增持仓"),
                details=details,
            )

        if symbol in {"TQQQ", *self._held_wheel_symbols()}:
            return self._item(
                row,
                instrument=symbol,
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="可能是 Put 行权接股，需要在车轮页面确认关联批次",
                details=_contract_details(contract, opened_on),
            )

        return self._preview_unmanaged(row, contract, opened_on, confidence)

    def _preview_leaps(
        self,
        row: StatementRow,
        contract: Contract,
        opened_on: date,
        confidence: str,
        used_slots: dict[str, set[int]],
    ) -> dict[str, Any]:
        if contract.symbol != "QQQ" and not is_club_symbol(contract.symbol):
            return self._preview_unmanaged(row, contract, opened_on, confidence)
        existing_rows = self._matching_positions(contract)
        if len(existing_rows) > 1:
            exact = _position_group_matches(existing_rows, contract)
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip",
                status="matched" if exact else "review",
                confidence="exact" if exact else "low",
                selected=False,
                can_import=False,
                message=(
                    f"已按 {len(existing_rows)} 个 LEAPS 批次合计匹配"
                    if exact
                    else f"IBKR 聚合合约对应 {len(existing_rows)} 个 LEAPS 批次，需要人工核对"
                ),
                details=_contract_details(contract, opened_on),
            )
        existing = existing_rows[0] if existing_rows else None
        slot_key = contract.symbol if contract.symbol != "QQQ" else "QQQ"
        max_slots = 2 if contract.symbol != "QQQ" else 5
        tranche = existing.tranche if existing else _claim_slot(used_slots, slot_key, max_slots)
        details = _contract_details(contract, opened_on)
        details.update(
            bucket=Bucket.LEAPS.value,
            tranche=tranche,
            position_id=existing.id if existing else None,
            underlying_entry_price=None,
        )
        if tranche is None:
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="该标的可用槽位不足，需要先执行 FIFO",
                details=details,
            )
        exact = existing is not None and _position_matches(existing, contract)
        return self._item(
            row,
            instrument=_instrument_label(contract),
            action="skip" if exact else ("update_position" if existing else "create_position"),
            status="matched" if exact else "ready",
            confidence=confidence,
            selected=not exact,
            can_import=not exact,
            message=(
                "系统持仓已经一致"
                if exact
                else "更新现有 LEAPS 持仓"
                if existing
                else "新增 LEAPS 持仓"
            ),
            details=details,
        )

    def _preview_position_roll(
        self,
        position_row: StatementRow,
        position_contract: Contract,
        roll: PositionRoll,
    ) -> dict[str, Any]:
        if position_contract.symbol != "QQQ" and not is_club_symbol(
            position_contract.symbol
        ):
            return self._item(
                roll.opening_row,
                instrument=f"{position_contract.symbol} Long Call 展期",
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="检测到 Long Call 展期，但该标的不属于 LEAPS 策略",
                details=_contract_details(
                    position_contract,
                    roll.traded_at.date(),
                ),
            )

        current_rows = self._matching_positions(position_contract)
        current = current_rows[0] if len(current_rows) == 1 else None
        if current is not None and current.rolled_from_position_id is not None:
            previous = self.session.get(
                PositionRecord,
                current.rolled_from_position_id,
            )
            exact = _position_matches(current, position_contract)
            return self._item(
                roll.opening_row,
                instrument=f"{position_contract.symbol} Long Call 展期",
                action="skip" if exact else "update_position",
                status="matched" if exact else "ready",
                confidence="exact",
                selected=not exact,
                can_import=not exact,
                message="LEAPS 展期已经一致" if exact else "更新展期后的 LEAPS 持仓",
                details=self._position_roll_details(
                    previous,
                    current,
                    position_contract,
                    roll,
                ),
            )
        if current is not None:
            return self._item(
                roll.opening_row,
                instrument=f"{position_contract.symbol} Long Call 展期",
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="新合约已存在，但未关联旧 LEAPS 持仓",
                details=_contract_details(position_contract, roll.traded_at.date()),
            )

        previous_rows = self._matching_positions(roll.closing_contract)
        if len(previous_rows) != 1:
            return self._item(
                roll.opening_row,
                instrument=f"{position_contract.symbol} Long Call 展期",
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="检测到 Long Call 展期，但未找到唯一的旧 LEAPS 持仓",
                details=_contract_details(position_contract, roll.traded_at.date()),
            )
        previous = previous_rows[0]
        if previous.quantity != abs(roll.closing_contract.quantity):
            return self._item(
                roll.opening_row,
                instrument=f"{position_contract.symbol} Long Call 展期",
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="LEAPS 展期数量与旧持仓不一致",
                details=_contract_details(position_contract, roll.traded_at.date()),
            )
        return self._item(
            roll.opening_row,
            instrument=f"{position_contract.symbol} Long Call 展期",
            action="roll_position",
            status="ready",
            confidence="exact",
            selected=True,
            can_import=True,
            message=(
                f"{roll.closing_contract.expiration.isoformat()} "
                f"${roll.closing_contract.strike:g} Call 展期至 "
                f"{roll.opening_contract.expiration.isoformat()} "
                f"${roll.opening_contract.strike:g} Call"
            ),
            details=self._position_roll_details(
                previous,
                None,
                position_contract,
                roll,
            ),
        )

    @staticmethod
    def _position_roll_details(
        previous: PositionRecord | None,
        current: PositionRecord | None,
        position_contract: Contract,
        roll: PositionRoll,
    ) -> dict[str, Any]:
        quantity = abs(roll.opening_contract.quantity)
        return {
            **_contract_details(position_contract, roll.traded_at.date()),
            "bucket": Bucket.LEAPS.value,
            "position_id": previous.id if previous else None,
            "current_position_id": current.id if current else None,
            "tranche": previous.tranche if previous else current.tranche if current else None,
            "underlying_entry_price": None,
            "old_expiration": roll.closing_contract.expiration.isoformat(),
            "old_strike": float(roll.closing_contract.strike),
            "exit_price": float(roll.closing_contract.cost_price),
            "cost_price": float(roll.opening_contract.cost_price),
            "net_debit": float(
                (roll.opening_contract.cost_price - roll.closing_contract.cost_price)
                * HUNDRED
                * quantity
            ),
            "realized_profit": (
                float(
                    (roll.closing_contract.cost_price - previous.entry_price)
                    * previous.quantity
                    * previous.multiplier
                )
                if previous
                else None
            ),
        }

    def _preview_wheel_put(
        self,
        row: StatementRow,
        contract: Contract,
        opened_on: date,
        confidence: str,
    ) -> dict[str, Any]:
        is_core_put = contract.symbol in CORE_PUT_SYMBOLS
        if not is_core_put and contract.symbol != "TQQQ" and not is_wheel_club_symbol(contract.symbol):
            return self._preview_unmanaged(row, contract, opened_on, confidence)
        existing_rows = self._matching_puts(contract)
        if len(existing_rows) > 1:
            exact = _put_group_matches(existing_rows, contract)
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip",
                status="matched" if exact else "review",
                confidence="exact" if exact else "low",
                selected=False,
                can_import=False,
                message=(
                    f"已按 {len(existing_rows)} 个 Sell Put 批次合计匹配"
                    if exact
                    else f"IBKR 聚合合约对应 {len(existing_rows)} 个 Sell Put 批次，需要人工核对"
                ),
                details=_contract_details(contract, opened_on),
            )
        existing = existing_rows[0] if existing_rows else None
        details = _contract_details(contract, opened_on)
        details.update(
            put_id=existing.id if existing else None,
            capital_bucket=(
                existing.capital_bucket
                if existing
                else Bucket.CORE.value
                if is_core_put
                else Bucket.WHEEL.value
            ),
            underlying_entry_price=(float(existing.entry_tqqq_price) if existing else None),
            earnings_confirmed=(
                existing.earnings_confirmed
                if existing
                else is_core_put or contract.symbol == "TQQQ"
            ),
        )
        exact = existing is not None and (
            existing.open_quantity == abs(int(contract.quantity))
            and _price_matches(existing.premium, contract.cost_price)
        )
        if exact:
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip",
                status="matched",
                confidence="exact",
                selected=False,
                can_import=False,
                message="系统车轮持仓已经一致",
                details=details,
            )
        if existing and existing.assigned_contracts:
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="该 Put 已有部分行权记录，不能直接覆盖数量",
                details=details,
            )
        if (
            not existing
            and contract.symbol == "TQQQ"
            and WheelPortfolioService(self.session).has_exposure(contract.symbol)
        ):
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="同标的已有活动车轮周期，请人工选择批次",
                details=details,
            )
        needs_reference = not existing and details["underlying_entry_price"] is None
        needs_earnings = (
            not is_core_put
            and contract.symbol != "TQQQ"
            and not details["earnings_confirmed"]
        )
        return self._item(
            row,
            instrument=_instrument_label(contract),
            action="update_wheel_put" if existing else "create_wheel_put",
            status="ready",
            confidence="estimated" if needs_reference or needs_earnings else confidence,
            selected=True,
            can_import=True,
            message=(
            "新增核心仓 Sell Put 建仓；接股后转入核心仓，禁止自动 Covered Call"
                if is_core_put
                else
                "新增 Sell Put；报表未提供开仓正股价与财报确认，保留为待刷新参考"
                if needs_reference and needs_earnings
                else "新增 Sell Put；报表未提供开仓正股价，保留为待刷新参考"
                if needs_reference
                else "新增 Sell Put；报表未提供财报确认"
                if needs_earnings
                else "更新现有 Sell Put"
            ),
            details=details,
        )

    def _preview_wheel_roll(
        self,
        position_row: StatementRow,
        position_contract: Contract,
        roll: PutRoll,
    ) -> dict[str, Any]:
        if (
            position_contract.symbol not in CORE_PUT_SYMBOLS
            and position_contract.symbol != "TQQQ"
            and not is_wheel_club_symbol(position_contract.symbol)
        ):
            return self._preview_unmanaged(
                position_row,
                position_contract,
                roll.traded_at.date(),
                "exact",
            )

        current_rows = self._matching_puts(position_contract)
        current = current_rows[0] if len(current_rows) == 1 else None
        if current is not None and current.rolled_from_put_id is not None:
            previous = self.session.get(WheelPutLot, current.rolled_from_put_id)
            details = self._roll_details(previous, current, roll)
            return self._item(
                roll.opening_row,
                instrument=_instrument_label(position_contract),
                action="skip",
                status="matched",
                confidence="exact",
                selected=False,
                can_import=False,
                message="该 Sell Put 展期已经同步",
                details=details,
            )

        previous_rows = self._matching_puts(roll.closing_contract)
        if len(previous_rows) != 1:
            return self._preview_wheel_put(
                position_row,
                position_contract,
                roll.traded_at.date(),
                "exact",
            )
        previous = previous_rows[0]
        quantity = abs(int(roll.opening_contract.quantity))
        closing_quantity = abs(int(roll.closing_contract.quantity))
        if quantity != closing_quantity or quantity != previous.open_quantity:
            details = self._roll_details(previous, None, roll)
            return self._item(
                roll.opening_row,
                instrument=_instrument_label(position_contract),
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="检测到部分展期或数量不一致，需要人工核对",
                details=details,
            )
        if roll.opening_contract.expiration <= roll.closing_contract.expiration:
            details = self._roll_details(previous, None, roll)
            return self._item(
                roll.opening_row,
                instrument=_instrument_label(position_contract),
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="新合约到期日没有延后，未自动认定为展期",
                details=details,
            )

        return self._item(
            roll.opening_row,
            instrument=f"{position_contract.symbol} Sell Put 展期",
            action="roll_wheel_put",
            status="ready",
            confidence="exact",
            selected=True,
            can_import=True,
            message=(
                f"{roll.closing_contract.expiration.isoformat()} ${roll.closing_contract.strike:g} "
                f"展期至 {roll.opening_contract.expiration.isoformat()} ${roll.opening_contract.strike:g}；"
                f"净收 ${((roll.opening_contract.cost_price - roll.closing_contract.cost_price) * HUNDRED * quantity):,.2f}"
            ),
            details=self._roll_details(previous, None, roll),
        )

    @staticmethod
    def _roll_details(
        previous: WheelPutLot | None,
        current: WheelPutLot | None,
        roll: PutRoll,
    ) -> dict[str, Any]:
        quantity = abs(int(roll.opening_contract.quantity))
        return {
            "put_id": previous.id if previous else None,
            "current_put_id": current.id if current else None,
            "symbol": roll.opening_contract.symbol,
            "capital_bucket": (
                previous.capital_bucket
                if previous
                else Bucket.CORE.value
                if roll.opening_contract.symbol in CORE_PUT_SYMBOLS
                else Bucket.WHEEL.value
            ),
            "asset_type": "option",
            "option_type": "put",
            "quantity": quantity,
            "opened_on": roll.traded_at.date().isoformat(),
            "expiration": roll.opening_contract.expiration.isoformat(),
            "strike": float(roll.opening_contract.strike),
            "cost_price": float(roll.opening_contract.cost_price),
            "close_price": float(roll.opening_contract.close_price),
            "old_expiration": roll.closing_contract.expiration.isoformat(),
            "old_strike": float(roll.closing_contract.strike),
            "buyback_premium": float(roll.closing_contract.cost_price),
            "new_premium": float(roll.opening_contract.cost_price),
            "net_credit": float(
                (roll.opening_contract.cost_price - roll.closing_contract.cost_price)
                * HUNDRED
                * quantity
            ),
            "underlying_entry_price": (
                float(previous.entry_tqqq_price) if previous else None
            ),
            "earnings_confirmed": previous.earnings_confirmed if previous else False,
        }

    def _preview_leaps_call(
        self,
        row: StatementRow,
        contract: Contract,
        opened_on: date,
        confidence: str,
    ) -> dict[str, Any] | None:
        """Classify a short call covered by a LEAPS call or QLD replacement."""
        quantity = abs(int(contract.quantity))
        existing = self._matching_leaps_calls(contract)
        if len(existing) > 1:
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip",
                status="review",
                confidence="low",
                selected=False,
                can_import=False,
                message="同一 LEAPS Sell Call 合约存在多条记录，需要人工核对",
                details=_contract_details(contract, opened_on),
            )
        details = _contract_details(contract, opened_on)
        details.update(
            category=LEAPS_CALL_WHEEL_CATEGORY,
            direction="short",
            holding_id=existing[0].id if existing else None,
            linked_position_id=existing[0].linked_position_id if existing else None,
        )
        if existing:
            record = existing[0]
            exact = record.quantity == quantity and _price_matches(
                record.entry_price, contract.cost_price
            )
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip" if exact else "update_leaps_call",
                status="matched" if exact else "ready",
                confidence="exact" if exact else confidence,
                selected=not exact,
                can_import=not exact,
                message="LEAPS Sell Call 已经一致" if exact else "更新 LEAPS Sell Call",
                details=details,
            )

        candidate = self._single_covering_leaps_position(contract.symbol, quantity)
        if candidate is None:
            return None
        details["linked_position_id"] = candidate.id
        return self._item(
            row,
            instrument=_instrument_label(contract),
            action="create_leaps_call",
            status="ready",
            confidence=confidence,
            selected=True,
            can_import=True,
            message=f"新增 {contract.symbol} LEAPS Sell Call 轮动，关联 Long Call #{candidate.id}",
            details=details,
        )

    def _preview_covered_call(
        self,
        row: StatementRow,
        contract: Contract,
        opened_on: date,
        confidence: str,
    ) -> dict[str, Any]:
        existing_rows = self._matching_calls(contract)
        if len(existing_rows) > 1:
            exact = _call_group_matches(existing_rows, contract)
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip",
                status="matched" if exact else "review",
                confidence="exact" if exact else "low",
                selected=False,
                can_import=False,
                message=(
                    f"已按 {len(existing_rows)} 个 Covered Call 批次合计匹配"
                    if exact
                    else f"IBKR 聚合合约对应 {len(existing_rows)} 个 Covered Call 批次，需要人工核对"
                ),
                details=_contract_details(contract, opened_on),
            )
        existing = existing_rows[0] if existing_rows else None
        details = _contract_details(contract, opened_on)
        details["call_id"] = existing.id if existing else None
        if existing:
            exact = existing.quantity == abs(int(contract.quantity)) and _price_matches(
                existing.premium, contract.cost_price
            )
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="skip" if exact else "update_wheel_call",
                status="matched" if exact else "ready",
                confidence="exact" if exact else confidence,
                selected=not exact,
                can_import=not exact,
                message="系统 Covered Call 已经一致" if exact else "更新现有 Covered Call",
                details=details,
            )
        share = self._single_covering_share(contract.symbol, abs(int(contract.quantity)))
        details["share_lot_id"] = share.id if share else None
        if share:
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="create_wheel_call",
                status="ready",
                confidence=confidence,
                selected=True,
                can_import=True,
                message="新增 Covered Call",
                details=details,
            )
        unmanaged = self._preview_unmanaged(row, contract, opened_on, "low")
        if unmanaged["status"] != "matched":
            unmanaged.update(
                status="ready",
                confidence="estimated",
                selected=True,
                message="未找到唯一接股批次，自动同步到其他 Short Call",
            )
        return unmanaged

    def _preview_unmanaged(
        self,
        row: StatementRow,
        contract: Contract,
        opened_on: date,
        confidence: str,
    ) -> dict[str, Any]:
        direction = "long" if contract.quantity > ZERO else "short"
        existing = self.session.scalar(
            select(UnmanagedPositionRecord).where(
                UnmanagedPositionRecord.status == "open",
                UnmanagedPositionRecord.symbol == contract.symbol,
                UnmanagedPositionRecord.asset_type == contract.asset_type,
                UnmanagedPositionRecord.direction == direction,
                UnmanagedPositionRecord.option_type == contract.option_type,
                UnmanagedPositionRecord.expiration == contract.expiration,
                UnmanagedPositionRecord.strike == contract.strike,
            )
        )
        details = _contract_details(contract, opened_on)
        details.update(
            holding_id=existing.id if existing else None,
            direction=direction,
            category=(
                "cash_equivalent"
                if contract.symbol == "BOXX" and contract.asset_type == "equity"
                else "other"
            ),
        )
        exact = existing is not None and (
            existing.quantity == abs(contract.quantity)
            and (
                existing.entry_price is None
                or _price_matches(existing.entry_price, contract.cost_price)
            )
        )
        category_label = "现金等价物" if details["category"] == "cash_equivalent" else "其他持仓"
        return self._item(
            row,
            instrument=_instrument_label(contract),
            action="skip" if exact else ("update_unmanaged" if existing else "create_unmanaged"),
            status="matched" if exact else "ready",
            confidence="exact" if exact else confidence,
            selected=not exact,
            can_import=not exact,
            message=(
                f"{category_label}已经一致"
                if exact
                else f"更新{category_label}"
                if existing
                else f"新增到{category_label}"
            ),
            details=details,
        )

    def _preview_trade(
        self,
        row: StatementRow,
        roll_trade_fingerprints: set[str],
        opening_trades: dict[tuple[Any, ...], list[tuple[StatementRow, Contract, datetime]]],
    ) -> dict[str, Any] | None:
        if row.fingerprint in roll_trade_fingerprints:
            return None
        contract = _contract(row.values)
        codes = {
            value.strip().upper()
            for value in _value(row.values, "Code").split(";")
            if value.strip()
        }
        traded_at = _parse_datetime(_value(row.values, "Date/Time", "Trade Date", "Date"))
        if contract is None or traded_at is None or "C" not in codes:
            return None
        quantity = abs(contract.quantity)
        details = _contract_details(contract, traded_at.date())
        details.update(
            quantity=float(quantity),
            closed_on=traded_at.date().isoformat(),
            exit_price=float(contract.cost_price),
        )

        if contract.option_type == "put" and contract.quantity > ZERO:
            puts = self._matching_puts(contract)
            if len(puts) == 1 and puts[0].open_quantity == int(quantity):
                record = puts[0]
                details["put_id"] = record.id
                details["realized_profit"] = float(
                    (record.premium - contract.cost_price) * HUNDRED * quantity
                )
                return self._item(
                    row,
                    instrument=_instrument_label(contract),
                    action="close_wheel_put",
                    status="ready",
                    confidence="exact",
                    selected=True,
                    can_import=True,
                    message=f"买回平仓，预计已实现 ${details['realized_profit']:,.2f}",
                    details=details,
                )

        if contract.option_type == "call" and contract.quantity < ZERO:
            positions = self._matching_positions(contract)
            if len(positions) == 1 and positions[0].quantity == quantity:
                record = positions[0]
                details["position_id"] = record.id
                details["realized_profit"] = float(
                    (contract.cost_price - record.entry_price)
                    * quantity
                    * record.multiplier
                )
                return self._item(
                    row,
                    instrument=_instrument_label(contract),
                    action="close_position",
                    status="ready",
                    confidence="exact",
                    selected=True,
                    can_import=True,
                    message=f"LEAPS 平仓，预计已实现 ${details['realized_profit']:,.2f}",
                    details=details,
                )

        if contract.option_type == "call" and contract.quantity > ZERO:
            leaps_calls = self._matching_leaps_calls(contract)
            if len(leaps_calls) == 1 and leaps_calls[0].quantity == quantity:
                record = leaps_calls[0]
                details["holding_id"] = record.id
                details["linked_position_id"] = record.linked_position_id
                details["realized_profit"] = float(
                    (record.entry_price - contract.cost_price)
                    * HUNDRED
                    * quantity
                )
                return self._item(
                    row,
                    instrument=_instrument_label(contract),
                    action="close_leaps_call",
                    status="ready",
                    confidence="exact",
                    selected=True,
                    can_import=True,
                    message=f"LEAPS Sell Call 买回平仓，预计已实现 ${details['realized_profit']:,.2f}",
                    details=details,
                )
            calls = self._matching_calls(contract)
            if len(calls) == 1 and calls[0].quantity == int(quantity):
                record = calls[0]
                details["call_id"] = record.id
                details["realized_profit"] = float(
                    (record.premium - contract.cost_price) * HUNDRED * quantity
                )
                return self._item(
                    row,
                    instrument=_instrument_label(contract),
                    action="close_wheel_call",
                    status="ready",
                    confidence="exact",
                    selected=True,
                    can_import=True,
                    message=f"Covered Call 买回平仓，预计已实现 ${details['realized_profit']:,.2f}",
                    details=details,
                )

        direction = "long" if contract.quantity < ZERO else "short"
        unmanaged = self._matching_unmanaged(contract, direction)
        if len(unmanaged) == 1 and unmanaged[0].quantity == quantity:
            record = unmanaged[0]
            details["holding_id"] = record.id
            details["direction"] = direction
            if record.entry_price is not None:
                signed = Decimal("1") if direction == "long" else Decimal("-1")
                details["realized_profit"] = float(
                    (contract.cost_price - record.entry_price)
                    * quantity
                    * record.multiplier
                    * signed
                )
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="close_unmanaged",
                status="ready",
                confidence="exact",
                selected=True,
                can_import=True,
                message="同步到其他持仓退出记录",
                details=details,
            )

        intraday = [
            candidate
            for candidate in opening_trades.get(contract.key, [])
            if candidate[2].date() == traded_at.date()
            and candidate[2] <= traded_at
            and abs(candidate[1].quantity) == quantity
        ]
        if len(intraday) == 1:
            opening_row, opening_contract, opened_at = intraday[0]
            direction = "long" if opening_contract.quantity > ZERO else "short"
            signed = Decimal("1") if direction == "long" else Decimal("-1")
            details.update(
                direction=direction,
                entry_price=float(opening_contract.cost_price),
                opened_on=opened_at.date().isoformat(),
                realized_profit=float(
                    (contract.cost_price - opening_contract.cost_price)
                    * quantity
                    * (HUNDRED if contract.asset_type == "option" else Decimal("1"))
                    * signed
                ),
                opening_trade_fingerprint=opening_row.fingerprint,
            )
            return self._item(
                row,
                instrument=_instrument_label(contract),
                action="record_closed_unmanaged",
                status="ready",
                confidence="exact",
                selected=True,
                can_import=True,
                message=f"当日开平仓，已实现 ${details['realized_profit']:,.2f}",
                details=details,
            )

        return self._item(
            row,
            instrument=_instrument_label(contract),
            action="skip",
            status="review",
            confidence="low",
            selected=False,
            can_import=False,
            message="检测到平仓成交，但未找到唯一的系统持仓",
            details=details,
        )

    def _apply(
        self,
        item: dict[str, Any],
        override: dict[str, Any],
        *,
        deposit_affects_balance: bool = True,
    ) -> tuple[str, int]:
        details = {**item["details"], **override}
        action = item["action"]
        if action == "deposit":
            amount = Decimal(str(details["amount"]))
            occurred_on = date.fromisoformat(details["occurred_on"])
            note = f"IBKR 导入：{details['note']}"
            if deposit_affects_balance:
                PortfolioStore(self.session).deposit(amount, occurred_on, note)
            else:
                self.session.add(
                    LedgerEvent(
                        event_type="deposit",
                        bucket=Bucket.CASH.value,
                        amount=amount,
                        occurred_on=occurred_on,
                        details={"note": note, "source": "IBKR", "snapshot_included": True},
                    )
                )
                self.session.flush()
            event = self.session.scalar(
                select(LedgerEvent).where(LedgerEvent.event_type == "deposit").order_by(LedgerEvent.id.desc())
            )
            return "ledger_event", event.id if event else 0
        if action in {"create_position", "update_position"}:
            return "position", self._apply_position(action, details)
        if action in {"create_unmanaged", "update_unmanaged"}:
            return "unmanaged_position", self._apply_unmanaged(action, details)
        if action in {"create_leaps_call", "update_leaps_call"}:
            return "leaps_call_wheel", self._apply_leaps_call(action, details)
        if action in {"create_wheel_put", "update_wheel_put", "roll_wheel_put"}:
            return "wheel_put", self._apply_put(action, details)
        if action in {"create_wheel_call", "update_wheel_call"}:
            return "wheel_call", self._apply_call(action, details)
        if action == "close_wheel_put":
            record = WheelPortfolioService(self.session).close_put(
                int(details["put_id"]),
                date.fromisoformat(details["closed_on"]),
                Decimal(str(details["exit_price"])),
            )
            return "wheel_put", record.id
        if action == "close_wheel_call":
            record = WheelPortfolioService(self.session).close_call(
                int(details["call_id"]),
                date.fromisoformat(details["closed_on"]),
                Decimal(str(details["exit_price"])),
            )
            return "wheel_call", record.id
        if action == "close_leaps_call":
            return "leaps_call_wheel", self._apply_leaps_call_close(details)
        if action == "close_position":
            return "position", self._apply_position_close(details)
        if action == "roll_position":
            return "position", self._apply_position_roll(details)
        if action == "close_unmanaged":
            OtherHoldingService(self.session).close(
                int(details["holding_id"]),
                date.fromisoformat(details["closed_on"]),
                Decimal(str(details["exit_price"])),
            )
            return "unmanaged_position", int(details["holding_id"])
        if action == "record_closed_unmanaged":
            return "unmanaged_position", self._apply_closed_unmanaged(details)
        raise ValueError(f"不支持的导入操作：{action}")

    def _apply_position_close(self, details: dict[str, Any]) -> int:
        record = self.session.get(PositionRecord, int(details["position_id"]))
        if record is None or record.status != "open":
            raise ValueError("待平仓 LEAPS 持仓不存在，请重新预览")
        quantity = Decimal(str(details["quantity"]))
        if quantity != record.quantity:
            raise ValueError("当前仅支持整笔 LEAPS 平仓导入")
        exit_price = Decimal(str(details["exit_price"]))
        closed_on = date.fromisoformat(details["closed_on"])
        realized = (exit_price - record.entry_price) * quantity * record.multiplier
        record.current_price = exit_price
        record.exit_price = exit_price
        record.closed_on = closed_on
        record.realized_profit = (record.realized_profit or ZERO) + realized
        record.quantity = ZERO
        record.status = "closed"
        event = LedgerEvent(
            event_type="position_close",
            bucket=record.bucket,
            amount=realized,
            occurred_on=closed_on,
            details={
                "position_id": record.id,
                "symbol": record.symbol,
                "quantity": float(quantity),
                "price": float(exit_price),
                "source": "IBKR",
            },
        )
        self.session.add(event)
        self.session.flush()
        RealizedCashService(self.session).post(
            f"leaps-position-exit:{event.id}",
            Bucket.LEAPS,
            realized,
            closed_on,
            profit_source="leaps",
            note=f"{record.symbol} LEAPS 平仓（IBKR 导入）",
        )
        self.session.commit()
        return record.id

    def _apply_position_roll(self, details: dict[str, Any]) -> int:
        previous = self.session.get(PositionRecord, int(details["position_id"]))
        if previous is None or previous.status != "open":
            raise ValueError("待展期 LEAPS 持仓不存在，请重新导入报表")
        quantity = Decimal(str(details["quantity"]))
        if quantity != previous.quantity:
            raise ValueError("当前仅支持整笔 LEAPS 展期导入")

        rolled_on = date.fromisoformat(details["opened_on"])
        exit_price = Decimal(str(details["exit_price"]))
        entry_price = Decimal(str(details["cost_price"]))
        current_price = Decimal(str(details["close_price"])) or entry_price
        realized = (
            (exit_price - previous.entry_price)
            * quantity
            * previous.multiplier
        )
        previous.current_price = exit_price
        previous.exit_price = exit_price
        previous.closed_on = rolled_on
        previous.realized_profit = (previous.realized_profit or ZERO) + realized
        previous.quantity = ZERO
        previous.status = "closed"

        current = PositionRecord(
            rolled_from_position_id=previous.id,
            bucket=Bucket.LEAPS.value,
            symbol=details["symbol"],
            asset_type="option",
            direction="long",
            option_type="call",
            quantity=quantity,
            multiplier=100,
            entry_price=entry_price,
            current_price=current_price,
            opened_on=rolled_on,
            expiration=date.fromisoformat(details["expiration"]),
            strike=Decimal(str(details["strike"])),
            tranche=previous.tranche,
            underlying_entry_price=None,
            entry_fees=ZERO,
            quote_source="ibkr_statement",
            quote_last=current_price,
            quote_as_of=datetime.combine(
                date.fromisoformat(details.get("report_as_of") or details["opened_on"]),
                datetime.min.time(),
            ),
        )
        self.session.add(current)
        self.session.flush()
        event = LedgerEvent(
            event_type="position_roll",
            bucket=Bucket.LEAPS.value,
            amount=realized,
            occurred_on=rolled_on,
            details={
                "position_id": previous.id,
                "rolled_to_position_id": current.id,
                "symbol": previous.symbol,
                "quantity": float(quantity),
                "exit_price": float(exit_price),
                "entry_price": float(entry_price),
                "net_debit": details.get("net_debit"),
                "source": "IBKR",
            },
        )
        self.session.add(event)
        self.session.flush()
        RealizedCashService(self.session).post(
            f"leaps-position-exit:{event.id}",
            Bucket.LEAPS,
            realized,
            rolled_on,
            profit_source="leaps",
            note=f"{previous.symbol} LEAPS 展期",
        )
        self.session.commit()
        return current.id

    def _apply_closed_unmanaged(self, details: dict[str, Any]) -> int:
        direction = details["direction"]
        quantity = Decimal(str(details["quantity"]))
        entry_price = Decimal(str(details["entry_price"]))
        exit_price = Decimal(str(details["exit_price"]))
        multiplier = 100 if details["asset_type"] == "option" else 1
        signed = Decimal("1") if direction == "long" else Decimal("-1")
        realized = (exit_price - entry_price) * quantity * multiplier * signed
        record = UnmanagedPositionRecord(
            category="other",
            symbol=details["symbol"],
            asset_type=details["asset_type"],
            direction=direction,
            option_type=details.get("option_type"),
            quantity=quantity,
            multiplier=multiplier,
            entry_price=entry_price,
            current_price=exit_price,
            opened_on=date.fromisoformat(details["opened_on"]),
            expiration=(
                date.fromisoformat(details["expiration"])
                if details.get("expiration")
                else None
            ),
            strike=(
                Decimal(str(details["strike"]))
                if details.get("strike") is not None
                else None
            ),
            status="closed",
            closed_on=date.fromisoformat(details["closed_on"]),
            exit_price=exit_price,
            realized_profit=realized.quantize(Decimal("0.01")),
            quote_source="ibkr_statement",
            quote_as_of=date.fromisoformat(details["closed_on"]),
        )
        self.session.add(record)
        self.session.commit()
        return record.id

    def _apply_position(self, action: str, details: dict[str, Any]) -> int:
        entry_price = Decimal(str(details["cost_price"]))
        current_price = Decimal(str(details["close_price"])) or entry_price
        quantity = Decimal(str(details["quantity"]))
        previous_quantity: Decimal | None = None
        if action == "create_position":
            if details["bucket"] == Bucket.CORE.value:
                PortfolioStore(self.session).auto_fund_core(entry_price * quantity, date.fromisoformat(details["opened_on"]))
            record = PositionRecord(
                rolled_from_position_id=details.get("rolled_from_position_id"),
                bucket=details["bucket"],
                symbol=details["symbol"],
                asset_type=details["asset_type"],
                direction="long",
                option_type=details.get("option_type"),
                quantity=quantity,
                multiplier=100 if details["asset_type"] == "option" else 1,
                entry_price=entry_price,
                current_price=current_price,
                opened_on=date.fromisoformat(details["opened_on"]),
                expiration=date.fromisoformat(details["expiration"]) if details.get("expiration") else None,
                strike=Decimal(str(details["strike"])) if details.get("strike") is not None else None,
                tranche=int(details["tranche"]) if details.get("tranche") else None,
                underlying_entry_price=None,
                entry_fees=ZERO,
            )
            self.session.add(record)
            self.session.flush()
            event_type = "position_open"
        else:
            record = self.session.get(PositionRecord, int(details["position_id"]))
            if record is None or record.status != "open":
                raise ValueError("待更新持仓不存在，请重新预览")
            previous_quantity = record.quantity
            record.quantity = quantity
            record.entry_price = entry_price
            record.current_price = current_price
            event_type = "broker_reconcile"
        report_as_of = date.fromisoformat(
            details.get("report_as_of") or date.today().isoformat()
        )
        record.quote_source = "ibkr_statement"
        record.quote_last = current_price
        record.quote_as_of = datetime.combine(report_as_of, datetime.min.time())
        if (
            record.bucket == Bucket.CORE.value
            and previous_quantity is not None
            and quantity < previous_quantity
        ):
            self.session.add(
                LedgerEvent(
                    event_type="core_rotation_leg",
                    bucket=Bucket.CORE.value,
                    amount=ZERO,
                    occurred_on=report_as_of,
                    details={
                        "symbol": record.symbol,
                        "previous_quantity": float(previous_quantity),
                        "quantity": float(quantity),
                        "source": "IBKR",
                    },
                )
            )
        self.session.add(
            LedgerEvent(
                event_type=event_type,
                bucket=record.bucket,
                amount=ZERO,
                occurred_on=date.fromisoformat(details["opened_on"]),
                details={"position_id": record.id, "symbol": record.symbol, "source": "IBKR"},
            )
        )
        self.session.commit()
        return record.id

    def _apply_unmanaged(self, action: str, details: dict[str, Any]) -> int:
        if action == "create_unmanaged":
            record = UnmanagedPositionRecord(
                category=details["category"],
                symbol=details["symbol"],
                asset_type=details["asset_type"],
                direction=details["direction"],
                option_type=details.get("option_type"),
                quantity=Decimal(str(details["quantity"])),
                multiplier=100 if details["asset_type"] == "option" else 1,
                entry_price=Decimal(str(details["cost_price"])) or None,
                current_price=Decimal(str(details["close_price"])) or None,
                opened_on=date.fromisoformat(details["opened_on"]),
                expiration=(date.fromisoformat(details["expiration"]) if details.get("expiration") else None),
                strike=(Decimal(str(details["strike"])) if details.get("strike") is not None else None),
                linked_position_id=(
                    int(details["linked_position_id"])
                    if details.get("linked_position_id") is not None
                    else None
                ),
                status="open",
                quote_source="ibkr_statement",
                quote_as_of=date.fromisoformat(
                    details.get("report_as_of") or date.today().isoformat()
                ),
            )
            self.session.add(record)
        else:
            record = self.session.get(UnmanagedPositionRecord, int(details["holding_id"]))
            if record is None:
                raise ValueError("待更新其他持仓不存在，请重新预览")
            record.quantity = Decimal(str(details["quantity"]))
            record.entry_price = Decimal(str(details["cost_price"])) or record.entry_price
            record.current_price = Decimal(str(details["close_price"])) or record.current_price
            if details.get("category"):
                record.category = details["category"]
            if details.get("linked_position_id") is not None:
                record.linked_position_id = int(details["linked_position_id"])
        record.quote_source = "ibkr_statement"
        record.quote_as_of = date.fromisoformat(
            details.get("report_as_of") or date.today().isoformat()
        )
        record.last_error = None
        self.session.commit()
        return record.id

    def _apply_leaps_call(self, action: str, details: dict[str, Any]) -> int:
        if action == "create_leaps_call":
            return self._apply_unmanaged(
                "create_unmanaged",
                {**details, "category": LEAPS_CALL_WHEEL_CATEGORY},
            )
        return self._apply_unmanaged(
            "update_unmanaged",
            {**details, "category": LEAPS_CALL_WHEEL_CATEGORY},
        )

    def _apply_leaps_call_close(self, details: dict[str, Any]) -> int:
        record = self.session.get(
            UnmanagedPositionRecord, int(details["holding_id"])
        )
        if record is None or record.status != "open":
            raise ValueError("待平仓 LEAPS Sell Call 不存在，请重新预览")
        quantity = Decimal(str(details["quantity"]))
        if quantity != record.quantity:
            raise ValueError("当前仅支持整笔 LEAPS Sell Call 平仓导入")
        exit_price = Decimal(str(details["exit_price"]))
        closed_on = date.fromisoformat(details["closed_on"])
        realized = (
            (record.entry_price - exit_price)
            * quantity
            * record.multiplier
        ).quantize(Decimal("0.01"))
        record.current_price = exit_price
        record.exit_price = exit_price
        record.closed_on = closed_on
        record.realized_profit = realized
        record.status = "closed"
        event = LedgerEvent(
            event_type="leaps_call_close",
            bucket=Bucket.LEAPS.value,
            amount=realized,
            occurred_on=closed_on,
            details={
                "holding_id": record.id,
                "linked_position_id": record.linked_position_id,
                "symbol": record.symbol,
                "quantity": float(quantity),
                "price": float(exit_price),
                "source": "IBKR",
            },
        )
        self.session.add(event)
        self.session.flush()
        RealizedCashService(self.session).post(
            f"leaps-call-wheel:{record.id}",
            Bucket.LEAPS,
            realized,
            closed_on,
            profit_source="leaps",
            note=f"{record.symbol} LEAPS Sell Call 平仓",
        )
        self.session.commit()
        return record.id

    def _apply_put(self, action: str, details: dict[str, Any]) -> int:
        service = WheelPortfolioService(self.session)
        if action == "roll_wheel_put":
            record = service.roll_put(
                int(details["put_id"]),
                rolled_on=date.fromisoformat(details["opened_on"]),
                buyback_premium=Decimal(str(details["buyback_premium"])),
                expiration=date.fromisoformat(details["expiration"]),
                strike=Decimal(str(details["strike"])),
                premium=Decimal(str(details["new_premium"])),
                quantity=abs(int(Decimal(str(details["quantity"])))),
                entry_underlying_price=(
                    Decimal(str(details["underlying_entry_price"]))
                    if details.get("underlying_entry_price")
                    else None
                ),
            )
            return record.id
        if action == "create_wheel_put":
            underlying = details.get("underlying_entry_price")
            capital_bucket = details.get("capital_bucket", Bucket.WHEEL.value)
            round_id = (
                None
                if capital_bucket == Bucket.CORE.value
                else self._active_wheel_round_id(details["symbol"])
            )
            record = service.open_put(
                symbol=details["symbol"],
                capital_bucket=capital_bucket,
                batch_number=1,
                trade_date=date.fromisoformat(details["opened_on"]),
                expiration=date.fromisoformat(details["expiration"]),
                strike=Decimal(str(details["strike"])),
                premium=Decimal(str(details["cost_price"])),
                quantity=abs(int(Decimal(str(details["quantity"])))),
                entry_tqqq_price=Decimal(str(underlying or 0)),
                earnings_confirmed=bool(details.get("earnings_confirmed")),
                round_id=round_id,
                broker_reconciled=True,
            )
        else:
            record = service.edit_put(
                int(details["put_id"]),
                trade_date=date.fromisoformat(details["opened_on"]),
                expiration=date.fromisoformat(details["expiration"]),
                strike=Decimal(str(details["strike"])),
                premium=Decimal(str(details["cost_price"])),
                quantity=abs(int(Decimal(str(details["quantity"])))),
                entry_tqqq_price=(
                    Decimal(str(details["underlying_entry_price"]))
                    if details.get("underlying_entry_price")
                    else None
                ),
            )
        return record.id

    def _apply_call(self, action: str, details: dict[str, Any]) -> int:
        service = WheelPortfolioService(self.session)
        values = {
            "trade_date": date.fromisoformat(details["opened_on"]),
            "expiration": date.fromisoformat(details["expiration"]),
            "strike": Decimal(str(details["strike"])),
            "premium": Decimal(str(details["cost_price"])),
            "quantity": abs(int(Decimal(str(details["quantity"])))),
        }
        if action == "create_wheel_call":
            record = service.open_call(int(details["share_lot_id"]), **values)
        else:
            record = service.edit_call(int(details["call_id"]), **values)
        return record.id

    def _matching_positions(self, contract: Contract) -> list[PositionRecord]:
        return list(
            self.session.scalars(
                select(PositionRecord).where(
                    PositionRecord.status == "open",
                    PositionRecord.bucket == Bucket.LEAPS.value,
                    PositionRecord.symbol == contract.symbol,
                    PositionRecord.asset_type == contract.asset_type,
                    PositionRecord.expiration == contract.expiration,
                    PositionRecord.strike == contract.strike,
                    PositionRecord.option_type == contract.option_type,
                )
            )
        )

    def _active_wheel_round_id(self, symbol: str) -> int | None:
        return self.session.scalar(
            select(WheelPutLot.round_id)
            .join(WheelRound, WheelPutLot.round_id == WheelRound.id)
            .where(
                WheelPutLot.symbol == symbol,
                WheelRound.status == "active",
                WheelPutLot.state != "voided",
            )
            .order_by(WheelPutLot.id.desc())
            .limit(1)
        )

    def _matching_puts(self, contract: Contract) -> list[WheelPutLot]:
        return list(
            self.session.scalars(
                select(WheelPutLot).where(
                    WheelPutLot.state == "open",
                    WheelPutLot.symbol == contract.symbol,
                    WheelPutLot.expiration == contract.expiration,
                    WheelPutLot.strike == contract.strike,
                )
            )
        )

    def _matching_calls(self, contract: Contract) -> list[WheelCallLot]:
        return list(
            self.session.scalars(
                select(WheelCallLot)
                .join(WheelShareLot, WheelCallLot.share_lot_id == WheelShareLot.id)
                .join(WheelPutLot, WheelShareLot.put_lot_id == WheelPutLot.id)
                .where(
                    WheelCallLot.state == "open",
                    WheelPutLot.symbol == contract.symbol,
                    WheelCallLot.expiration == contract.expiration,
                    WheelCallLot.strike == contract.strike,
                )
            )
        )

    def _matching_leaps_calls(
        self, contract: Contract
    ) -> list[UnmanagedPositionRecord]:
        return list(
            self.session.scalars(
                select(UnmanagedPositionRecord).where(
                    UnmanagedPositionRecord.status == "open",
                    UnmanagedPositionRecord.category == LEAPS_CALL_WHEEL_CATEGORY,
                    UnmanagedPositionRecord.symbol == contract.symbol,
                    UnmanagedPositionRecord.asset_type == "option",
                    UnmanagedPositionRecord.direction == "short",
                    UnmanagedPositionRecord.option_type == "call",
                    UnmanagedPositionRecord.expiration == contract.expiration,
                    UnmanagedPositionRecord.strike == contract.strike,
                )
            )
        )

    def _single_covering_leaps_position(
        self, symbol: str, contracts: int
    ) -> PositionRecord | None:
        if symbol == "QLD":
            required_quantity = Decimal(contracts * 100)
            candidates = list(
                self.session.scalars(
                    select(PositionRecord).where(
                        PositionRecord.status == "open",
                        PositionRecord.bucket == Bucket.LEAPS.value,
                        PositionRecord.symbol == "QLD",
                        PositionRecord.asset_type == "equity",
                        PositionRecord.direction == "long",
                        PositionRecord.option_type.is_(None),
                        PositionRecord.quantity >= required_quantity,
                    )
                )
            )
            return candidates[0] if len(candidates) == 1 else None
        candidates = list(
            self.session.scalars(
                select(PositionRecord).where(
                    PositionRecord.status == "open",
                    PositionRecord.bucket == Bucket.LEAPS.value,
                    PositionRecord.symbol == symbol,
                    PositionRecord.asset_type == "option",
                    PositionRecord.direction == "long",
                    PositionRecord.option_type == "call",
                    PositionRecord.quantity >= contracts,
                )
            )
        )
        return candidates[0] if len(candidates) == 1 else None

    def _matching_unmanaged(
        self, contract: Contract, direction: str
    ) -> list[UnmanagedPositionRecord]:
        return list(
            self.session.scalars(
                select(UnmanagedPositionRecord).where(
                    UnmanagedPositionRecord.status == "open",
                    UnmanagedPositionRecord.symbol == contract.symbol,
                    UnmanagedPositionRecord.asset_type == contract.asset_type,
                    UnmanagedPositionRecord.direction == direction,
                    UnmanagedPositionRecord.option_type == contract.option_type,
                    UnmanagedPositionRecord.expiration == contract.expiration,
                    UnmanagedPositionRecord.strike == contract.strike,
                )
            )
        )

    def _single_covering_share(self, symbol: str, contracts: int) -> WheelShareLot | None:
        candidates = list(
            self.session.scalars(
                select(WheelShareLot)
                .join(WheelPutLot, WheelShareLot.put_lot_id == WheelPutLot.id)
                .where(
                    WheelShareLot.state == "held",
                    WheelShareLot.remaining_quantity >= contracts * 100,
                    WheelPutLot.symbol == symbol,
                )
            )
        )
        return candidates[0] if len(candidates) == 1 else None

    def _held_wheel_symbols(self) -> set[str]:
        return set(
            self.session.scalars(
                select(WheelPutLot.symbol)
                .join(WheelShareLot, WheelShareLot.put_lot_id == WheelPutLot.id)
                .where(WheelShareLot.state == "held", WheelShareLot.remaining_quantity > 0)
            )
        )

    def _used_leaps_slots(self) -> dict[str, set[int]]:
        values: dict[str, set[int]] = {}
        for row in self.session.scalars(
            select(PositionRecord).where(
                PositionRecord.status == "open",
                PositionRecord.bucket == Bucket.LEAPS.value,
                PositionRecord.tranche.is_not(None),
            )
        ):
            key = "QQQ" if row.symbol in {"QQQ", "QLD"} else row.symbol
            values.setdefault(key, set()).add(int(row.tranche))
        return values

    def _trade_dates(self, rows: list[StatementRow]) -> dict[tuple[Any, ...], date]:
        result: dict[tuple[Any, ...], date] = {}
        for row in rows:
            if _section_key(row.section) != "trades":
                continue
            contract = _contract(row.values)
            traded_on = _parse_date(_value(row.values, "Date/Time", "Trade Date", "Date"))
            if contract is None or traded_on is None:
                continue
            previous = result.get(contract.key)
            if previous is None or traded_on < previous:
                result[contract.key] = traded_on
        return result

    def _put_rolls(self, rows: list[StatementRow]) -> dict[tuple[Any, ...], PutRoll]:
        closing: dict[tuple[str, datetime, int], list[tuple[StatementRow, Contract]]] = {}
        opening: dict[tuple[str, datetime, int], list[tuple[StatementRow, Contract]]] = {}
        for row in rows:
            if _section_key(row.section) != "trades":
                continue
            contract = _contract(row.values)
            traded_at = _parse_datetime(_value(row.values, "Date/Time", "Trade Date", "Date"))
            codes = {
                value.strip().upper()
                for value in _value(row.values, "Code").split(";")
                if value.strip()
            }
            if (
                contract is None
                or traded_at is None
                or contract.asset_type != "option"
                or contract.option_type != "put"
                or contract.expiration is None
                or contract.strike is None
            ):
                continue
            key = (contract.symbol, traded_at, abs(int(contract.quantity)))
            if contract.quantity > ZERO and "C" in codes:
                closing.setdefault(key, []).append((row, contract))
            elif contract.quantity < ZERO and "O" in codes:
                opening.setdefault(key, []).append((row, contract))

        rolls: dict[tuple[Any, ...], PutRoll] = {}
        for key in closing.keys() & opening.keys():
            closing_legs = closing[key]
            opening_legs = opening[key]
            if len(closing_legs) != 1 or len(opening_legs) != 1:
                continue
            closing_row, closing_contract = closing_legs[0]
            opening_row, opening_contract = opening_legs[0]
            if opening_contract.expiration <= closing_contract.expiration:
                continue
            rolls[opening_contract.key] = PutRoll(
                closing_row=closing_row,
                closing_contract=closing_contract,
                opening_row=opening_row,
                opening_contract=opening_contract,
                traded_at=key[1],
            )
        return rolls

    def _position_rolls(
        self, rows: list[StatementRow]
    ) -> dict[tuple[Any, ...], PositionRoll]:
        closing: dict[
            tuple[str, int], list[tuple[StatementRow, Contract, datetime]]
        ] = {}
        opening: dict[
            tuple[str, int], list[tuple[StatementRow, Contract, datetime]]
        ] = {}
        for row in rows:
            if _section_key(row.section) != "trades":
                continue
            contract = _contract(row.values)
            traded_at = _parse_datetime(
                _value(row.values, "Date/Time", "Trade Date", "Date")
            )
            codes = {
                value.strip().upper()
                for value in _value(row.values, "Code").split(";")
                if value.strip()
            }
            if (
                contract is None
                or traded_at is None
                or contract.asset_type != "option"
                or contract.option_type != "call"
                or contract.expiration is None
                or contract.strike is None
            ):
                continue
            key = (contract.symbol, abs(int(contract.quantity)))
            if contract.quantity < ZERO and "C" in codes:
                closing.setdefault(key, []).append((row, contract, traded_at))
            elif contract.quantity > ZERO and "O" in codes:
                opening.setdefault(key, []).append((row, contract, traded_at))

        rolls: dict[tuple[Any, ...], PositionRoll] = {}
        used_closing: set[str] = set()
        for key, opening_legs in opening.items():
            for opening_row, opening_contract, opening_at in opening_legs:
                candidates = [
                    candidate
                    for candidate in closing.get(key, [])
                    if candidate[0].fingerprint not in used_closing
                    and candidate[2].date() == opening_at.date()
                    and abs((candidate[2] - opening_at).total_seconds()) <= 300
                    and candidate[1].expiration < opening_contract.expiration
                ]
                if not candidates:
                    continue
                candidates.sort(
                    key=lambda candidate: abs(
                        (candidate[2] - opening_at).total_seconds()
                    )
                )
                if (
                    len(candidates) > 1
                    and abs((candidates[0][2] - opening_at).total_seconds())
                    == abs((candidates[1][2] - opening_at).total_seconds())
                ):
                    continue
                closing_row, closing_contract, closing_at = candidates[0]
                used_closing.add(closing_row.fingerprint)
                rolls[opening_contract.key] = PositionRoll(
                    closing_row=closing_row,
                    closing_contract=closing_contract,
                    opening_row=opening_row,
                    opening_contract=opening_contract,
                    traded_at=max(closing_at, opening_at),
                )
        return rolls

    def _opening_trades(
        self, rows: list[StatementRow]
    ) -> dict[tuple[Any, ...], list[tuple[StatementRow, Contract, datetime]]]:
        result: dict[tuple[Any, ...], list[tuple[StatementRow, Contract, datetime]]] = {}
        for row in rows:
            if _section_key(row.section) != "trades":
                continue
            contract = _contract(row.values)
            traded_at = _parse_datetime(_value(row.values, "Date/Time", "Trade Date", "Date"))
            codes = {
                value.strip().upper()
                for value in _value(row.values, "Code").split(";")
                if value.strip()
            }
            if contract is None or traded_at is None or "O" not in codes:
                continue
            result.setdefault(contract.key, []).append((row, contract, traded_at))
        return result

    @staticmethod
    def _item(
        row: StatementRow,
        *,
        instrument: str,
        action: str,
        status: str,
        confidence: str,
        selected: bool,
        can_import: bool,
        message: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        enriched_details = dict(details)
        if row.report_as_of is not None:
            enriched_details["report_as_of"] = row.report_as_of.isoformat()
        return {
            "fingerprint": row.fingerprint,
            "section": row.section,
            "row_index": row.row_index,
            "instrument": instrument,
            "action": action,
            "status": status,
            "confidence": confidence,
            "selected": selected,
            "can_import": can_import,
            "message": message,
            "details": enriched_details,
            "source": row.values,
        }


def parse_activity_statement(content: str) -> list[StatementRow]:
    text = content.lstrip("\ufeff")
    try:
        records = list(csv.reader(io.StringIO(text)))
    except csv.Error as error:
        raise ValueError(f"CSV 解析失败：{error}") from error
    report_as_of = _statement_end_date(records)
    headers: dict[str, list[str]] = {}
    rows: list[StatementRow] = []
    section_indices: dict[str, int] = {}
    semantic_occurrences: dict[str, int] = {}
    for record in records:
        if len(record) < 2:
            continue
        section = record[0].strip()
        marker = record[1].strip().lower()
        if not section:
            continue
        if marker == "header":
            headers[section] = _canonical_headers(section, record[2:])
            continue
        if marker != "data" or section not in headers:
            continue
        section_indices[section] = section_indices.get(section, 0) + 1
        values = {
            key: value.strip()
            for key, value in zip(headers[section], record[2:])
            if key
        }
        section_key = _section_key(section)
        if section_key == "open_positions":
            discriminator = _value(values, "DataDiscriminator").lower()
            if discriminator and discriminator != "summary":
                continue
        if section_key == "deposits":
            occurred_on = _value(values, "Settle Date", "Date", "Activity Date")
            description = _value(values, "Description", "Activity Description")
            if not occurred_on and not description:
                continue
        legacy_canonical = json.dumps(
            {"section": section, "values": values},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        semantic = _semantic_fingerprint_values(section, values, report_as_of)
        semantic_canonical = json.dumps(
            semantic,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        semantic_occurrences[semantic_canonical] = (
            semantic_occurrences.get(semantic_canonical, 0) + 1
        )
        canonical = json.dumps(
            {
                "semantic": semantic,
                "occurrence": semantic_occurrences[semantic_canonical],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        rows.append(
            StatementRow(
                section=section,
                row_index=section_indices[section],
                values=values,
                fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                legacy_fingerprint=hashlib.sha256(
                    legacy_canonical.encode("utf-8")
                ).hexdigest(),
                report_as_of=report_as_of,
            )
        )
    return rows


def _statement_end_date(records: list[list[str]]) -> date | None:
    return _statement_period(records)[1]


def _statement_period(records: list[list[str]]) -> tuple[date | None, date | None]:
    headers: dict[str, list[str]] = {}
    for record in records:
        if len(record) < 2:
            continue
        section = record[0].strip()
        marker = record[1].strip().lower()
        if marker == "header":
            headers[section] = _canonical_headers(section, record[2:])
            continue
        if marker != "data" or section not in headers:
            continue
        values = {
            key: value.strip()
            for key, value in zip(headers[section], record[2:])
            if key
        }
        field_name = _value(values, "Field Name", "Field", "Name").lower()
        if _section_key(section) != "statement" or field_name not in {
            "period",
            "statement period",
        }:
            continue
        period = _normalize_chinese_months(_value(values, "Field Value", "Value"))
        parts = [value.strip() for value in period.split(" - ", 1)]
        if len(parts) == 1:
            single_day = _parse_period_date(parts[0])
            return single_day, single_day
        if len(parts) != 2:
            continue
        return _parse_period_date(parts[0]), _parse_period_date(parts[1])
    return None, None


def _semantic_fingerprint_values(
    section: str,
    values: dict[str, str],
    report_as_of: date | None,
) -> dict[str, Any]:
    section_key = _section_key(section)
    if section_key == "deposits":
        return {
            "section": section_key,
            "date": _value(values, "Settle Date", "Date", "Activity Date"),
            "amount": str(_decimal(_value(values, "Amount", "Net Amount", "金额"))),
            "currency": _value(values, "Currency"),
            "description": _value(values, "Description", "Activity Description"),
        }
    contract = _contract(values)
    if section_key == "open_positions" and contract is not None:
        return {
            "section": section_key,
            "report_as_of": report_as_of.isoformat() if report_as_of else None,
            "contract": [str(value) if value is not None else None for value in contract.key],
            "quantity": str(contract.quantity),
            "cost_price": str(contract.cost_price),
            "close_price": str(contract.close_price),
        }
    if section_key == "trades" and contract is not None:
        return {
            "section": section_key,
            "contract": [str(value) if value is not None else None for value in contract.key],
            "date_time": _value(values, "Date/Time", "Trade Date", "Date"),
            "quantity": str(contract.quantity),
            "price": str(contract.cost_price),
            "code": _value(values, "Code"),
        }
    return {"section": section_key, "values": values}


def _section_key(value: str) -> str:
    localized = SECTION_ALIASES.get(value.strip())
    if localized is not None:
        return localized
    normalized = re.sub(r"[^a-z]", "", value.lower())
    if normalized == "openpositions":
        return "open_positions"
    if normalized in {"depositswithdrawals", "depositsandwithdrawals"}:
        return "deposits"
    if normalized == "trades":
        return "trades"
    if normalized in {"changeinnav", "netassetvaluechange"}:
        return "nav_change"
    return normalized


def _contract(values: dict[str, str]) -> Contract | None:
    category = _value(values, "Asset Category", "Asset Class", "Category").lower()
    symbol_text = _value(values, "Underlying Symbol", "Underlying", "Symbol")
    quantity = _decimal(_value(values, "Quantity", "Position"))
    cost_price = abs(_decimal(_value(values, "Cost Price", "T. Price", "Trade Price", "Price")))
    close_price = abs(_decimal(_value(values, "Close Price", "C. Price", "Mark Price")))
    if not symbol_text or quantity == ZERO:
        return None
    if "stock" in category or "equity" == category or category == "股票":
        return Contract(
            symbol=_normalize_symbol(_value(values, "Symbol")),
            asset_type="equity",
            quantity=quantity,
            cost_price=cost_price,
            close_price=close_price,
        )
    if "option" not in category and "期权" not in category:
        return None
    parsed = _option_identity(values)
    if parsed is None:
        return None
    symbol, expiration, strike, option_type = parsed
    return Contract(
        symbol=symbol,
        asset_type="option",
        quantity=quantity,
        cost_price=cost_price,
        close_price=close_price,
        expiration=expiration,
        strike=strike,
        option_type=option_type,
    )


def _option_identity(values: dict[str, str]) -> tuple[str, date, Decimal, str] | None:
    raw_symbol = _value(values, "Symbol")
    underlying = _value(values, "Underlying Symbol", "Underlying")
    expiration = _parse_date(_value(values, "Expiry", "Expiration", "Last Trading Day"))
    strike_value = _decimal(_value(values, "Strike", "Strike Price"))
    put_call = _value(values, "Put/Call", "Right", "Option Type").upper()
    if underlying and expiration and strike_value > ZERO and put_call[:1] in {"P", "C"}:
        return _normalize_symbol(underlying), expiration, strike_value, "put" if put_call.startswith("P") else "call"

    occ = re.fullmatch(r"\s*([A-Z.\-]{1,10})\s+(\d{6})([CP])(\d{8})\s*", raw_symbol.upper())
    if occ:
        expiration = datetime.strptime(occ.group(2), "%y%m%d").date()
        strike_value = Decimal(occ.group(4)) / Decimal("1000")
        return _normalize_symbol(occ.group(1)), expiration, strike_value, "put" if occ.group(3) == "P" else "call"

    readable = re.fullmatch(
        r"\s*([A-Z.\-]{1,10}(?:\s+[A-Z])?)\s+(\d{1,2})([A-Z]{3})(\d{2,4})\s+([\d.]+)\s+([CP])\s*",
        raw_symbol.upper(),
    )
    if readable:
        year = int(readable.group(4))
        year = year + 2000 if year < 100 else year
        month = datetime.strptime(readable.group(3), "%b").month
        expiration = date(year, month, int(readable.group(2)))
        return (
            _normalize_symbol(readable.group(1)),
            expiration,
            Decimal(readable.group(5)),
            "put" if readable.group(6) == "P" else "call",
        )
    return None


def _normalize_symbol(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "-")
    if normalized in {"BRK-B", "BRK.B"}:
        return "BRK.B"
    return normalized


def _parse_date(value: str) -> date | None:
    candidate = value.strip().split(",", 1)[0].strip()
    if not candidate:
        return None
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(candidate, pattern).date()
        except ValueError:
            continue
    match = re.match(r"(\d{4}-\d{2}-\d{2})", candidate)
    return date.fromisoformat(match.group(1)) if match else None


def _decimal(value: str) -> Decimal:
    cleaned = value.strip().replace(",", "").replace("$", "").replace(" ", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    if not cleaned or cleaned in {"-", "--"}:
        return ZERO
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return ZERO


def _value(values: dict[str, str], *keys: str) -> str:
    lowered = {key.strip().lower(): value for key, value in values.items()}
    for key in keys:
        value = lowered.get(key.lower(), "")
        if value:
            return value
    return ""


def _canonical_headers(section: str, headers: list[str]) -> list[str]:
    stripped = [value.strip() for value in headers]
    code_indices = [index for index, value in enumerate(stripped) if value == "代码"]
    section_key = _section_key(section)
    canonical: list[str] = []
    for index, value in enumerate(stripped):
        if value == "代码" and section_key in {"open_positions", "trades"}:
            canonical.append("Symbol" if index == code_indices[0] else "Code")
            continue
        canonical.append(HEADER_ALIASES.get(value, value))
    return canonical


def _normalize_chinese_months(value: str) -> str:
    normalized = value
    for chinese, english in sorted(
        CHINESE_MONTHS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        normalized = normalized.replace(chinese, english)
    return normalized


def _parse_period_date(value: str) -> date | None:
    candidate = _normalize_chinese_months(value.strip())
    for pattern in (
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(candidate, pattern).date()
        except ValueError:
            continue
    return None


def _parse_datetime(value: str) -> datetime | None:
    candidate = value.strip()
    for pattern in (
        "%Y-%m-%d, %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d, %H:%M",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(candidate, pattern)
        except ValueError:
            continue
    parsed_date = _parse_date(candidate)
    return datetime.combine(parsed_date, datetime.min.time()) if parsed_date else None


def _account_summary(
    content: str, rows: list[StatementRow]
) -> dict[str, Any] | None:
    records = list(csv.reader(io.StringIO(content.lstrip("\ufeff"))))
    period_start, period_end = _statement_period(records)
    fields: dict[str, Decimal] = {}
    aliases = {
        "开始价值": "starting_value",
        "starting value": "starting_value",
        "存款和取款": "deposits_withdrawals",
        "deposits & withdrawals": "deposits_withdrawals",
        "deposits and withdrawals": "deposits_withdrawals",
        "结束价值": "ending_value",
        "ending value": "ending_value",
    }
    for row in rows:
        if _section_key(row.section) != "nav_change":
            continue
        label = _value(row.values, "Field Name", "Field", "Name").strip().lower()
        key = aliases.get(label)
        if key is not None:
            fields[key] = _decimal(_value(row.values, "Field Value", "Value"))
    if period_start is None or period_end is None or fields.get("ending_value", ZERO) <= ZERO:
        return None
    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "starting_value": fields.get("starting_value", ZERO),
        "deposits_withdrawals": fields.get("deposits_withdrawals", ZERO),
        "ending_value": fields["ending_value"],
    }


def _claim_slot(values: dict[str, set[int]], key: str, maximum: int) -> int | None:
    used = values.setdefault(key, set())
    for slot in range(1, maximum + 1):
        if slot not in used:
            used.add(slot)
            return slot
    return None


def _position_matches(record: PositionRecord, contract: Contract) -> bool:
    return (
        record.quantity == abs(contract.quantity)
        and _price_matches(record.entry_price, contract.cost_price)
    )


def _position_group_matches(records: list[PositionRecord], contract: Contract) -> bool:
    quantity = sum((record.quantity for record in records), ZERO)
    if quantity != abs(contract.quantity) or quantity <= ZERO:
        return False
    total_cost = sum((record.entry_price * record.quantity for record in records), ZERO)
    average_cost = (total_cost / quantity).quantize(PRICE_QUANTUM)
    return average_cost == contract.cost_price.quantize(PRICE_QUANTUM)


def _put_group_matches(records: list[WheelPutLot], contract: Contract) -> bool:
    quantity = sum((record.open_quantity for record in records), 0)
    if quantity != abs(int(contract.quantity)) or quantity <= 0:
        return False
    premium = sum((record.premium * record.open_quantity for record in records), ZERO) / Decimal(quantity)
    return premium.quantize(PRICE_QUANTUM) == contract.cost_price.quantize(PRICE_QUANTUM)


def _call_group_matches(records: list[WheelCallLot], contract: Contract) -> bool:
    quantity = sum(record.quantity for record in records)
    if quantity != abs(int(contract.quantity)) or quantity <= 0:
        return False
    premium = sum((record.premium * record.quantity for record in records), ZERO) / Decimal(quantity)
    return premium.quantize(PRICE_QUANTUM) == contract.cost_price.quantize(PRICE_QUANTUM)


def _price_matches(left: Decimal | None, right: Decimal) -> bool:
    return left is not None and left.quantize(PRICE_QUANTUM) == right.quantize(
        PRICE_QUANTUM
    )


def _contract_details(contract: Contract, opened_on: date) -> dict[str, Any]:
    return {
        "symbol": contract.symbol,
        "asset_type": contract.asset_type,
        "option_type": contract.option_type,
        "quantity": float(abs(contract.quantity)),
        "reported_quantity": float(contract.quantity),
        "cost_price": float(contract.cost_price),
        "close_price": float(contract.close_price),
        "opened_on": opened_on.isoformat(),
        "expiration": contract.expiration.isoformat() if contract.expiration else None,
        "strike": float(contract.strike) if contract.strike is not None else None,
    }


def _instrument_label(contract: Contract) -> str:
    if contract.asset_type == "equity":
        return contract.symbol
    right = "Put" if contract.option_type == "put" else "Call"
    return f"{contract.symbol} {contract.expiration} ${contract.strike} {right}"
