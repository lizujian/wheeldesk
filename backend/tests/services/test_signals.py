from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db_models import Base, SignalRecord
from app.domain.core import CoreAssetInputs, CorePutDecision, evaluate_core_portfolio
from app.domain.core_rotation import CoreRotationDecision
from app.services.signals import SignalService


@pytest.fixture
def service() -> SignalService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield SignalService(session)


def test_stale_market_data_cannot_create_formal_signal(service: SignalService) -> None:
    result = service.emit(
        code="sell_put_opportunity",
        title="TQQQ 开仓 Sell Put",
        message="三项条件满足",
        severity="opportunity",
        market_date=date(2026, 7, 9),
        stale=True,
        formal=True,
    )

    assert result is None


def test_same_signal_on_same_market_date_is_deduplicated(service: SignalService) -> None:
    first = service.emit(
        "sell_put_opportunity",
        "TQQQ 开仓 Sell Put",
        "三项条件满足",
        "opportunity",
        date(2026, 7, 9),
    )
    second = service.emit(
        "sell_put_opportunity",
        "TQQQ 开仓 Sell Put",
        "三项条件满足",
        "opportunity",
        date(2026, 7, 9),
    )

    assert first.id == second.id
    count = service.session.scalar(select(func.count()).select_from(SignalRecord))
    assert count == 1


def test_same_day_signal_refreshes_changed_content_and_becomes_active(
    service: SignalService,
) -> None:
    first = service.emit(
        "core_buy_brk_b",
        "BRK.B 核心仓买入建议",
        "建议金额 10000",
        "opportunity",
        date(2026, 7, 9),
    )
    service.acknowledge(first.id)

    refreshed = service.emit(
        "core_buy_brk_b",
        "BRK.B 高位轻仓定投",
        "建议金额 5000",
        "opportunity",
        date(2026, 7, 9),
    )

    assert refreshed.id == first.id
    assert refreshed.title == "BRK.B 高位轻仓定投"
    assert refreshed.message == "建议金额 5000"
    assert refreshed.acknowledged is False
    assert service.list_active() == [refreshed]


def test_critical_signals_sort_before_lower_severity(service: SignalService) -> None:
    service.emit("vix_high", "VIX 高位", "评估现金储备", "warning", date(2026, 7, 9))
    service.emit("ma200_break", "跌破牛熊分界线", "立即评估止损", "critical", date(2026, 7, 9))

    signals = service.list_active()

    assert [signal.severity for signal in signals] == ["critical", "warning"]


def test_recent_signals_keep_acknowledged_history_after_active_items(
    service: SignalService,
) -> None:
    acknowledged = service.emit(
        "core_buy_brk_b",
        "BRK.B 核心仓买入建议",
        "建议买入 BRK.B",
        "opportunity",
        date(2026, 8, 27),
    )
    service.acknowledge(acknowledged.id)
    active = service.emit(
        "sell_put_opportunity",
        "TQQQ 开仓 Sell Put",
        "三项条件满足",
        "opportunity",
        date(2026, 8, 26),
    )

    recent = service.list_recent(include_acknowledged=True)

    assert [signal.id for signal in recent] == [active.id, acknowledged.id]
    assert service.list_active() == [active]


def core_decision(drawdown: str = "0.10"):
    return evaluate_core_portfolio(
        [CoreAssetInputs(
            symbol="BRK.B", current_value=Decimal("0"), price=Decimal("500"),
            drawdown=Decimal(drawdown), daily_change=Decimal("0"), rsi14=Decimal("55"),
            ma200=Decimal("450"), below_ma200_two_days=False,
            return_20d=Decimal("0"), return_126d=Decimal("0"),
            last_purchase_date=None, last_purchase_tier=None,
        )],
        as_of=date(2026, 9, 4), total_target=Decimal("100000"),
        total_equity=Decimal("200000"), available_funding=Decimal("25000"),
        vix=Decimal("18"), ratio_z=Decimal("0"), route_confirmation_days=0,
        rotation_confirmation_days=0, last_account_purchase_date=None,
        last_rotation_date=None, ratio_reset_since_rotation=True,
    ).recommendation


def test_core_reminders_wait_five_weekdays_even_after_acknowledgement(service):
    decision = core_decision()
    first = service.sync_core_buy(decision, date(2026, 9, 4))
    service.acknowledge(first.id)
    assert service.sync_core_buy(decision, date(2026, 9, 4)) is None
    assert service.sync_core_buy(decision, date(2026, 9, 7)) is None
    assert service.sync_core_buy(decision, date(2026, 9, 10)) is None
    assert service.list_active() == []
    renewed = service.sync_core_buy(decision, date(2026, 9, 11))
    assert renewed is not None
    assert renewed.id != first.id


def test_deeper_core_opportunity_overrides_reminder_cooldown(service):
    first = service.sync_core_buy(core_decision(), date(2026, 9, 4))
    deeper = service.sync_core_buy(core_decision("0.16"), date(2026, 9, 4))
    assert deeper is not None
    assert first.acknowledged
    assert service.list_active() == [deeper]
    assert service.sync_core_buy(core_decision(), date(2026, 9, 7)) is None


def test_suppressed_core_advice_retires_old_badges_but_preserves_other_signals(service):
    old = service.emit("core_buy_brk_b", "买入", "旧建议", "opportunity", date(2026, 9, 3))
    risk = service.emit("ma200_break", "趋势风险", "风险", "critical", date(2026, 9, 3))
    service.sync_core_buy(None, date(2026, 9, 4), stale=True)
    assert not old.acknowledged
    service.sync_core_buy(None, date(2026, 9, 4))
    assert old.acknowledged
    assert service.list_active() == [risk]
    assert old in service.list_recent(include_acknowledged=True)


def test_core_put_and_stock_signals_share_cooldown_and_allow_deeper_stock_entry(service):
    put = CorePutDecision("opportunity", True, "BRK.B", Decimal("480"), Decimal("48000"), Decimal("50000"), 1)
    first = service.sync_core_buy(None, date(2026, 9, 4), put=put)
    assert "Sell Put" in first.title
    assert service.sync_core_buy(None, date(2026, 9, 7), put=put) is None
    deeper = service.sync_core_buy(core_decision(), date(2026, 9, 7))
    assert deeper is not None
    assert first.acknowledged
    assert service.list_active() == [deeper]


def test_rotation_reminders_record_weights_and_retire_after_partial_execution(service):
    from dataclasses import replace

    decision = CoreRotationDecision(
        code="opportunity", actionable=True, ratio=Decimal(".84"), band="sell_0.83",
        current_brk_weight=Decimal("1"), target_brk_weight=Decimal(".55"),
        next_brk_weight=Decimal(".8"), amount=Decimal("20000"),
        sell_symbol="BRK.B", buy_symbol="VOO", weight_change=Decimal(".2"),
    )
    first = service.sync_core_rotation(decision, date(2026, 9, 4))
    assert "0.8400" in first.message
    assert "55.0%" in first.message
    assert "20.0%" in first.message
    assert service.sync_core_rotation(decision, date(2026, 9, 7)) is None
    service.sync_core_rotation(replace(decision, amount=Decimal("10000")), date(2026, 9, 7))
    assert first.acknowledged
    assert service.list_active() == []
