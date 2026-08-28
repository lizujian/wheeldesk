from datetime import date

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db_models import Base, SignalRecord
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
