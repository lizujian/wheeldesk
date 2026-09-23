from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db_models import SignalRecord
from app.domain.core import CoreAssetDecision, CorePutDecision, TIER_RANK
from app.domain.core_rotation import CoreRotationDecision

SEVERITY_ORDER = {"critical": 0, "warning": 1, "opportunity": 2, "info": 3}
WHEEL_SIGNAL_CODES = ("sell_put_opportunity",)
WHEEL_SIGNAL_PREFIXES = ("trillion_club_wheel_",)


class SignalService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def sync_core_buy(
        self,
        decision: CoreAssetDecision | None,
        market_date: date,
        *,
        stale: bool = False,
        put: CorePutDecision | None = None,
    ) -> SignalRecord | None:
        if stale:
            return None
        history = list(self.session.scalars(
            select(SignalRecord).where(
                SignalRecord.code.startswith("core_buy_"),
                SignalRecord.market_date <= market_date,
            )
        ))
        put_actionable = put is not None and put.actionable
        actionable = put_actionable or (decision is not None and decision.actionable)
        code = (
            f"core_buy_{put.symbol.lower().replace('.', '_')}_put" if put_actionable
            else f"core_buy_{decision.symbol.lower().replace('.', '_')}_{decision.code}"
            if actionable else None
        )
        # Keep history, but remove obsolete DCA advice from the global badge.
        for record in history:
            if record.code != code:
                record.acknowledged = True
        self.session.commit()
        if not actionable:
            return None
        rank = TIER_RANK["put"] if put_actionable else TIER_RANK.get(decision.code, 0)
        for record in history:
            days = sum(
                (record.market_date + timedelta(days=offset)).weekday() < 5
                for offset in range(1, (market_date - record.market_date).days + 1)
            )
            previous_rank = TIER_RANK.get(record.code.rsplit("_", 1)[-1], 1)
            if days < 5 and previous_rank >= rank:
                return None
        for record in history:
            record.acknowledged = True
        self.session.commit()
        if put_actionable:
            return self.emit(
                code, f"{put.symbol} 核心仓 Sell Put 建仓机会",
                f"评估 1 张 7～21 天 Put，支撑参考 {put.reference_strike}；"
                f"行权价不高于该参考时，接股资金约 {put.collateral}。"
                f"保留直接买股资金至少 {put.direct_buy_reserve}；接股后归核心仓。",
                "opportunity", market_date,
            )
        return self.emit(
            code,
            f"{decision.symbol} 核心仓买入建议",
            (
                f"{decision.symbol} 建议金额 {decision.executable_amount}；"
                f"单日涨跌 {decision.daily_change:.1%}、"
                f"回撤 {decision.drawdown:.1%}、RSI14 {decision.rsi14:.1f}。"
                "建议金额已扣除待接股安排；同档或更弱提醒间隔 5 个工作日。"
            ),
            "opportunity",
            market_date,
        )

    def sync_core_rotation(self, decision: CoreRotationDecision, market_date: date, *, stale: bool = False):
        if stale:
            return None
        history = list(self.session.scalars(select(SignalRecord).where(
            SignalRecord.code.startswith("core_rotation_"), SignalRecord.market_date <= market_date,
        ).order_by(SignalRecord.market_date.desc(), SignalRecord.id.desc())))
        code = f"core_rotation_{decision.band}" if decision.actionable else None
        for record in history:
            if record.code != code:
                record.acknowledged = True
        self.session.commit()
        if not decision.actionable:
            return None
        previous = next((record for record in history if record.code == code), None)
        if previous and (market_date - previous.market_date).days < 7:
            if f"建议等额轮动 {decision.amount}，" not in previous.message:
                previous.acknowledged = True
                self.session.commit()
            return None
        for record in history:
            record.acknowledged = True
        self.session.commit()
        return self.emit(
            code, f"核心仓轮动观察：{decision.sell_symbol} → {decision.buy_symbol}",
            f"二级观察，不作为主要买入信号。收盘比率 {decision.ratio:.4f}；BRK.B 当前 {decision.current_brk_weight:.1%}，"
            f"档位目标 {decision.target_brk_weight:.1%}，本次调整至 {decision.next_brk_weight:.1%}。"
            f"建议等额轮动 {decision.amount}，幅度 {decision.weight_change:.1%}；"
            f"近 20 交易日已使用 {decision.used_weight:.1%}。仅为低频观察建议，成交以 IBKR 报表为准。",
            "info", decision.ratio_as_of or market_date,
        )

    def emit(
        self,
        code: str,
        title: str,
        message: str,
        severity: str,
        market_date: date,
        stale: bool = False,
        formal: bool = True,
    ) -> SignalRecord | None:
        if severity not in SEVERITY_ORDER:
            raise ValueError("未知的信号级别")
        if stale and formal:
            return None
        existing = self.session.scalar(
            select(SignalRecord).where(
                SignalRecord.code == code,
                SignalRecord.market_date == market_date,
            )
        )
        if existing is not None:
            changed = (
                existing.title != title
                or existing.message != message
                or existing.severity != severity
            )
            if changed:
                existing.title = title
                existing.message = message
                existing.severity = severity
                existing.acknowledged = False
                self.session.commit()
            return existing
        signal = SignalRecord(
            code=code,
            title=title,
            message=message,
            severity=severity,
            market_date=market_date,
        )
        self.session.add(signal)
        self.session.commit()
        return signal

    def retire_wheel_signals(self) -> None:
        """Archive legacy Wheel signals while keeping their history readable."""
        predicates = [SignalRecord.code.in_(WHEEL_SIGNAL_CODES)]
        predicates.extend(
            SignalRecord.code.like(f"{prefix}%")
            for prefix in WHEEL_SIGNAL_PREFIXES
        )
        records = list(self.session.scalars(select(SignalRecord).where(or_(*predicates))))
        changed = False
        for record in records:
            if not record.acknowledged:
                record.acknowledged = True
                changed = True
        if changed:
            self.session.commit()

    def list_active(self) -> list[SignalRecord]:
        return self.list_recent(include_acknowledged=False)

    def list_recent(
        self,
        *,
        include_acknowledged: bool = False,
        limit: int = 100,
    ) -> list[SignalRecord]:
        query = select(SignalRecord)
        if not include_acknowledged:
            query = query.where(SignalRecord.acknowledged.is_(False))
        records = list(self.session.scalars(query))
        return sorted(
            records,
            key=lambda signal: (
                signal.acknowledged,
                SEVERITY_ORDER[signal.severity] if not signal.acknowledged else 0,
                -signal.market_date.toordinal(),
                -signal.id,
            ),
        )[:limit]

    def acknowledge(self, signal_id: int) -> SignalRecord:
        signal = self.session.get(SignalRecord, signal_id)
        if signal is None:
            raise ValueError("找不到信号")
        signal.acknowledged = True
        self.session.commit()
        return signal
