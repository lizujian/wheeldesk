from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db_models import Base
from app.services.exit_positions import ExitPositionService


@pytest.fixture
def service() -> ExitPositionService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield ExitPositionService(session)


@pytest.mark.parametrize("position_type", ["stock", "long_call", "sell_put", "covered_call"])
def test_supports_four_lightweight_record_types(
    service: ExitPositionService, position_type: str
) -> None:
    record = service.create(
        name="Legacy position",
        position_type=position_type,
        current_value=Decimal("1000"),
        target_value=Decimal("1500"),
        note="manual reference",
    )

    assert record.position_type == position_type
    assert record.status == "active"
    assert record.recovered_cash == Decimal("0.00")


def test_target_comparison_works_with_negative_sell_put_pnl(service: ExitPositionService) -> None:
    record = service.create(
        "TQQQ Sell Put",
        "sell_put",
        current_value=Decimal("-3000"),
        target_value=Decimal("-500"),
    )

    assert service.payload(record)["target_reached"] is False

    service.update(record.id, current_value=Decimal("-400"))

    assert service.payload(record)["target_reached"] is True


def test_partial_exit_accumulates_cash_and_keeps_remaining_manual_value(
    service: ExitPositionService,
) -> None:
    record = service.create(
        "AAPL stock",
        "stock",
        current_value=Decimal("30000"),
        target_value=Decimal("40000"),
    )

    updated = service.partial_exit(
        record.id,
        recovered_cash=Decimal("10000"),
        remaining_value=Decimal("21000"),
        note="sold part",
    )

    assert updated.status == "partial"
    assert updated.current_value == Decimal("21000.00")
    assert updated.recovered_cash == Decimal("10000.00")
    assert service.payload(updated)["core_transfer_suggestion"] == Decimal("10000.00")


def test_complete_exit_zeroes_current_value_and_keeps_total_recovered_cash(
    service: ExitPositionService,
) -> None:
    record = service.create(
        "QQQ Long Call",
        "long_call",
        current_value=Decimal("4000"),
        target_value=Decimal("8000"),
    )
    service.partial_exit(record.id, Decimal("1500"), Decimal("2500"))

    completed = service.complete_exit(record.id, recovered_cash=Decimal("2600"))

    assert completed.status == "exited"
    assert completed.current_value == Decimal("0.00")
    assert completed.recovered_cash == Decimal("4100.00")


def test_stock_and_long_call_values_cannot_be_negative(service: ExitPositionService) -> None:
    with pytest.raises(ValueError, match="当前总价值不能为负数"):
        service.create("AAPL", "stock", Decimal("-1"), Decimal("100"))


def test_stock_cost_price_can_be_created_and_updated(service: ExitPositionService) -> None:
    record = service.create(
        "AAPL stock",
        "stock",
        Decimal("30000"),
        Decimal("40000"),
        cost_price=Decimal("185.50"),
    )

    assert service.payload(record)["cost_price"] == Decimal("185.50")

    updated = service.update(record.id, cost_price=Decimal("190.25"))

    assert service.payload(updated)["cost_price"] == Decimal("190.25")


@pytest.mark.parametrize("cost_price", [Decimal("0"), Decimal("-1")])
def test_stock_cost_price_must_be_positive(
    service: ExitPositionService,
    cost_price: Decimal,
) -> None:
    with pytest.raises(ValueError, match="每股平均成本价必须大于零"):
        service.create(
            "AAPL stock",
            "stock",
            Decimal("30000"),
            Decimal("40000"),
            cost_price=cost_price,
        )


def test_non_stock_cost_price_is_not_stored(service: ExitPositionService) -> None:
    record = service.create(
        "QQQ Long Call",
        "long_call",
        Decimal("4000"),
        Decimal("8000"),
        cost_price=Decimal("12.50"),
    )

    assert service.payload(record)["cost_price"] is None
