from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db_models import Base, BucketBalance, PortfolioProfile
from app.services.wheel_portfolio import WheelPortfolioService


@pytest.fixture
def service() -> WheelPortfolioService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            PortfolioProfile(
                id=1,
                age=30,
                opening_equity=Decimal("312500"),
                opening_date=date(2026, 7, 1),
                currency="USD",
            )
        )
        session.add_all(
            [
                BucketBalance(bucket="cash", amount=Decimal("10000")),
                BucketBalance(bucket="wheel", amount=Decimal("100000")),
                BucketBalance(bucket="unallocated", amount=Decimal("202500")),
            ]
        )
        session.commit()
        yield WheelPortfolioService(session)


def open_first(service: WheelPortfolioService):
    return service.open_put(
        batch_number=1,
        trade_date=date(2026, 7, 18),
        expiration=date(2026, 8, 21),
        strike=Decimal("50"),
        premium=Decimal("1.50"),
        quantity=12,
        entry_tqqq_price=Decimal("55"),
    )


def test_first_and_second_batches_share_a_round_but_remain_separate(
    service: WheelPortfolioService,
) -> None:
    first = open_first(service)
    second = service.open_put(
        round_id=first.round_id,
        batch_number=2,
        trade_date=date(2026, 7, 25),
        expiration=date(2026, 8, 28),
        strike=Decimal("45"),
        premium=Decimal("1.80"),
        quantity=8,
        entry_tqqq_price=Decimal("49"),
    )

    assert service.round_number(first.round_id) == 1
    assert first.collateral == Decimal("60000.00")
    assert second.round_id == first.round_id
    assert second.collateral == Decimal("36000.00")
    assert first.state == second.state == "open"


def test_first_batch_call_can_coexist_when_second_put_expires(
    service: WheelPortfolioService,
) -> None:
    first = open_first(service)
    second = service.open_put(
        round_id=first.round_id,
        batch_number=2,
        trade_date=date(2026, 7, 25),
        expiration=date(2026, 8, 28),
        strike=Decimal("45"),
        premium=Decimal("1.80"),
        quantity=8,
        entry_tqqq_price=Decimal("49"),
    )
    shares = service.assign_put(first.id, date(2026, 8, 21), contracts=12)
    call = service.open_call(
        share_lot_id=shares.id,
        trade_date=date(2026, 8, 22),
        expiration=date(2026, 9, 18),
        strike=Decimal("52"),
        premium=Decimal("1.20"),
        quantity=6,
    )

    service.expire_put(second.id, date(2026, 8, 28))

    assert call.state == "open"
    assert shares.state == "held"
    assert second.state == "expired"


def test_released_capital_uses_a_new_round_first_batch(
    service: WheelPortfolioService,
) -> None:
    first = open_first(service)
    service.expire_put(first.id, date(2026, 8, 21))

    next_first = service.open_put(
        batch_number=1,
        trade_date=date(2026, 9, 1),
        expiration=date(2026, 10, 9),
        strike=Decimal("48"),
        premium=Decimal("1.40"),
        quantity=8,
        entry_tqqq_price=Decimal("53"),
    )

    assert service.round_number(next_first.round_id) == 2


def test_trade_can_use_capacity_previously_reserved_for_leaps(
    service: WheelPortfolioService,
) -> None:
    put = service.open_put(
        batch_number=1,
        trade_date=date(2026, 7, 18),
        expiration=date(2026, 8, 21),
        strike=Decimal("50"),
        premium=Decimal("1.50"),
        quantity=22,
        entry_tqqq_price=Decimal("55"),
    )

    overview = service.overview()

    assert put.id is not None
    assert overview["budget"]["exposure"] == Decimal("110000.00")
    assert overview["budget"]["over_budget"] == Decimal("0.00")
    assert overview["budget"]["available"] == Decimal("30625.00")


def test_overview_separates_assigned_capital_commitment_and_cash_margin(
    service: WheelPortfolioService,
) -> None:
    service.open_put(
        batch_number=1,
        trade_date=date(2026, 7, 18),
        expiration=date(2026, 8, 21),
        strike=Decimal("50"),
        premium=Decimal("1.50"),
        quantity=24,
        entry_tqqq_price=Decimal("55"),
    )

    capital = service.overview()["capital"]

    assert capital == {
        "assigned": Decimal("100000.00"),
        "put_collateral": Decimal("120000.00"),
        "share_capital": Decimal("0.00"),
        "strategy_committed": Decimal("120000.00"),
        "committed": Decimal("120000.00"),
        "available": Decimal("0.00"),
        "cash_occupancy": Decimal("20000.00"),
        "cash_available": Decimal("0.00"),
        "margin_shortfall": Decimal("10000.00"),
    }


def test_assignment_converts_put_collateral_to_share_capital_without_double_counting(
    service: WheelPortfolioService,
) -> None:
    put = open_first(service)
    before = service.overview()["capital"]

    service.assign_put(put.id, date(2026, 8, 21), contracts=12)
    after = service.overview()["capital"]

    assert before["put_collateral"] == Decimal("60000.00")
    assert before["share_capital"] == Decimal("0.00")
    assert after["put_collateral"] == Decimal("0.00")
    assert after["share_capital"] == Decimal("60000.00")
    assert before["committed"] == after["committed"] == Decimal("60000.00")


def test_expiry_call_away_and_void_release_derived_commitment(
    service: WheelPortfolioService,
) -> None:
    expired_put = open_first(service)
    service.expire_put(expired_put.id, date(2026, 8, 21))
    assert service.overview()["capital"]["committed"] == Decimal("0.00")

    assigned_put = service.open_put(
        batch_number=1,
        trade_date=date(2026, 9, 1),
        expiration=date(2026, 10, 9),
        strike=Decimal("48"),
        premium=Decimal("1.40"),
        quantity=2,
        entry_tqqq_price=Decimal("53"),
    )
    shares = service.assign_put(assigned_put.id, date(2026, 10, 9), contracts=2)
    call = service.open_call(
        shares.id,
        date(2026, 10, 10),
        date(2026, 11, 20),
        Decimal("50"),
        Decimal("1.20"),
        2,
    )
    service.call_away(call.id, date(2026, 11, 20))
    assert service.overview()["capital"]["committed"] == Decimal("0.00")

    voided_put = service.open_put(
        batch_number=1,
        trade_date=date(2026, 12, 1),
        expiration=date(2027, 1, 8),
        strike=Decimal("45"),
        premium=Decimal("1.10"),
        quantity=2,
        entry_tqqq_price=Decimal("50"),
    )
    assert service.overview()["capital"]["committed"] == Decimal("9000.00")
    service.void_put(voided_put.id, "录入错误")
    assert service.overview()["capital"]["committed"] == Decimal("0.00")


def test_multiple_calls_cannot_exceed_one_share_lot_coverage(
    service: WheelPortfolioService,
) -> None:
    shares = service.assign_put(open_first(service).id, date(2026, 8, 21), contracts=12)
    service.open_call(
        shares.id,
        date(2026, 8, 22),
        date(2026, 9, 18),
        Decimal("52"),
        Decimal("1.20"),
        6,
    )
    service.open_call(
        shares.id,
        date(2026, 8, 22),
        date(2026, 10, 16),
        Decimal("55"),
        Decimal("0.90"),
        6,
    )

    with pytest.raises(ValueError, match="超过可覆盖股数"):
        service.open_call(
            shares.id,
            date(2026, 8, 22),
            date(2026, 10, 16),
            Decimal("56"),
            Decimal("0.80"),
            1,
        )


def test_put_close_sends_realized_profit_to_cash_without_growing_wheel_budget(
    service: WheelPortfolioService,
) -> None:
    put = open_first(service)

    closed = service.close_put(put.id, date(2026, 7, 25), Decimal("0.50"))
    overview = service.overview()

    assert closed.realized_profit == Decimal("1200.00")
    assert overview["budget"]["budget"] == Decimal("141165.00")
    assert overview["budget"]["funded"] == Decimal("100000.00")
    assert overview["budget"]["exposure"] == Decimal("0.00")
    assert service.session.get(BucketBalance, "cash").amount == Decimal("11200.00")
    assert service.session.get(BucketBalance, "wheel").amount == Decimal("100000.00")


def test_core_accumulation_put_uses_core_capital_and_never_enters_the_wheel() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                BucketBalance(bucket="core", amount=Decimal("60000")),
                BucketBalance(bucket="cash", amount=Decimal("10000")),
                BucketBalance(bucket="wheel", amount=Decimal("20000")),
                BucketBalance(bucket="leaps", amount=Decimal("25000")),
            ]
        )
        session.commit()
        service = WheelPortfolioService(session)

        put = service.open_put(
            batch_number=1,
            trade_date=date(2026, 9, 4),
            expiration=date(2026, 10, 2),
            strike=Decimal("500"),
            premium=Decimal("4.65"),
            quantity=1,
            entry_tqqq_price=Decimal("0"),
            symbol="BRK.B",
            capital_bucket="core",
            broker_reconciled=True,
        )

        assert service.overview()["rounds"] == []
        assert service.overview()["core_puts"][0]["collateral"] == Decimal("50000.00")
        with pytest.raises(ValueError, match="IBKR 股票持仓快照"):
            service.assign_put(put.id, date(2026, 10, 2), 1)

        service.close_put(put.id, date(2026, 9, 18), Decimal("1.65"))

        assert session.get(BucketBalance, "cash").amount == Decimal("10300.00")
        assert session.get(BucketBalance, "core").amount == Decimal("60000.00")
        assert session.get(BucketBalance, "wheel").amount == Decimal("20000.00")


def test_put_loss_reduces_wheel_instead_of_cash(service: WheelPortfolioService) -> None:
    put = open_first(service)

    service.close_put(put.id, date(2026, 7, 25), Decimal("2.00"))

    assert service.session.get(BucketBalance, "cash").amount == Decimal("10000.00")
    assert service.session.get(BucketBalance, "wheel").amount == Decimal("99400.00")


def test_assignment_and_call_expiry_each_post_their_profit_once(
    service: WheelPortfolioService,
) -> None:
    shares = service.assign_put(open_first(service).id, date(2026, 8, 21), contracts=12)
    call = service.open_call(
        shares.id,
        date(2026, 8, 22),
        date(2026, 9, 18),
        Decimal("52"),
        Decimal("1.20"),
        6,
    )

    service.expire_call(call.id, date(2026, 9, 18))

    assert service.session.get(BucketBalance, "cash").amount == Decimal("12520.00")


def test_voiding_a_settled_chain_reverses_cash_postings(
    service: WheelPortfolioService,
) -> None:
    put = open_first(service)
    shares = service.assign_put(put.id, date(2026, 8, 21), contracts=12)
    call = service.open_call(
        shares.id,
        date(2026, 8, 22),
        date(2026, 9, 18),
        Decimal("52"),
        Decimal("1.20"),
        6,
    )
    service.expire_call(call.id, date(2026, 9, 18))
    assert service.session.get(BucketBalance, "cash").amount == Decimal("12520.00")

    service.void_chain(put.id, reason="录入错误")

    assert service.session.get(BucketBalance, "cash").amount == Decimal("10000.00")


def test_edit_recalculates_collateral_and_void_releases_it(
    service: WheelPortfolioService,
) -> None:
    put = open_first(service)

    edited = service.edit_put(put.id, strike=Decimal("48"), quantity=10)
    assert edited.collateral == Decimal("48000.00")

    voided = service.void_put(put.id, reason="录入错误")
    assert voided.state == "voided"
    assert service.overview()["budget"]["exposure"] == Decimal("0.00")


def test_put_with_descendants_requires_chain_void(
    service: WheelPortfolioService,
) -> None:
    put = open_first(service)
    shares = service.assign_put(put.id, date(2026, 8, 21), contracts=12)
    call = service.open_call(
        shares.id,
        date(2026, 8, 22),
        date(2026, 9, 18),
        Decimal("52"),
        Decimal("1.20"),
        6,
    )

    with pytest.raises(ValueError, match="存在后续记录"):
        service.void_put(put.id, reason="录入错误")

    affected = service.void_chain(put.id, reason="录入错误")

    assert affected == {"puts": 1, "shares": 1, "calls": 1}
    assert put.state == shares.state == call.state == "voided"
    assert service.overview()["budget"]["exposure"] == Decimal("0.00")
