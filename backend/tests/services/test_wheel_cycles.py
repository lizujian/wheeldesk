from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db_models import Base
from app.services.wheel_cycles import WheelCycleService


@pytest.fixture
def service() -> WheelCycleService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield WheelCycleService(session)


def test_put_assignment_uses_gross_premium_to_reduce_share_basis(service: WheelCycleService) -> None:
    cycle = service.open_put(
        trade_date=date(2026, 7, 10),
        expiration=date(2026, 8, 14),
        strike=Decimal("100"),
        premium=Decimal("2"),
        quantity=1,
    )

    assigned = service.assign_put(cycle.id, date(2026, 8, 14))

    assert assigned.state == "shares_held"
    assert assigned.share_quantity == 100
    assert assigned.share_cost_total == Decimal("9800.00")
    assert assigned.adjusted_share_basis == Decimal("98.00")


def test_safe_put_expiration_closes_cycle_with_gross_premium(service: WheelCycleService) -> None:
    cycle = service.open_put(
        date(2026, 7, 10), date(2026, 8, 14), Decimal("100"), Decimal("2"), 1
    )

    closed = service.expire_put(cycle.id, date(2026, 8, 14))

    assert closed.state == "closed"
    assert closed.realized_profit == Decimal("200.00")

    with pytest.raises(ValueError, match="当前状态"):
        service.expire_put(cycle.id, date(2026, 8, 14))


def test_buying_back_put_records_net_realized_profit(service: WheelCycleService) -> None:
    cycle = service.open_put(
        date(2026, 7, 10), date(2026, 8, 14), Decimal("100"), Decimal("2"), 1
    )

    closed = service.close_put(
        cycle.id,
        closed_on=date(2026, 7, 25),
        buyback_premium=Decimal("0.50"),
    )

    assert closed.state == "closed"
    assert closed.realized_profit == Decimal("150.00")


def test_assignment_call_and_call_away_calculate_complete_cycle_profit(service: WheelCycleService) -> None:
    cycle = service.open_put(
        date(2026, 7, 10), date(2026, 8, 14), Decimal("100"), Decimal("2"), 1
    )
    service.assign_put(cycle.id, date(2026, 8, 14))
    service.open_call(
        cycle.id,
        trade_date=date(2026, 8, 17),
        expiration=date(2026, 9, 18),
        strike=Decimal("105"),
        premium=Decimal("1"),
        quantity=1,
    )

    closed = service.call_away(cycle.id, date(2026, 9, 18))

    assert closed.state == "closed"
    assert closed.realized_profit == Decimal("800.00")
    assert closed.closed_on == date(2026, 9, 18)


def test_buying_back_call_returns_to_shares_and_keeps_gross_call_premium(service: WheelCycleService) -> None:
    cycle = service.open_put(
        date(2026, 7, 10), date(2026, 8, 14), Decimal("100"), Decimal("2"), 1
    )
    service.assign_put(cycle.id, date(2026, 8, 14))
    service.open_call(
        cycle.id,
        date(2026, 8, 17),
        date(2026, 9, 18),
        Decimal("105"),
        Decimal("1"),
        1,
    )

    shares = service.close_call(
        cycle.id,
        closed_on=date(2026, 8, 28),
        buyback_premium=Decimal("0.25"),
    )

    assert shares.state == "shares_held"
    assert shares.call_premium_net == Decimal("75.00")
    assert shares.adjusted_share_basis == Decimal("97.25")
