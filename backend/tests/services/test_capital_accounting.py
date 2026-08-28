from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db_models import (
    Base,
    BucketBalance,
    ProfitLedgerEntry,
    PositionRecord,
    WheelPutLot,
    WheelRound,
)
from app.domain.models import Bucket
from app.services.capital_accounting import CapitalAccountingService
from app.services.portfolio_store import PortfolioStore
from app.services.profit_ledger import ProfitLedgerService
from app.services.realized_cash import RealizedCashService


def make_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_capital(session: Session, cash: Decimal = Decimal("30000")) -> None:
    session.add_all(
        [
            BucketBalance(bucket="core", amount=Decimal("168000")),
            BucketBalance(bucket="cash", amount=cash),
            BucketBalance(bucket="wheel", amount=Decimal("81600")),
            BucketBalance(bucket="leaps", amount=Decimal("20400")),
            BucketBalance(bucket="unallocated", amount=Decimal("0")),
            PositionRecord(
                bucket="core",
                symbol="BRK.B",
                asset_type="equity",
                direction="long",
                quantity=80,
                multiplier=1,
                entry_price=469,
                current_price=512.37,
                opened_on=date(2026, 7, 29),
                entry_fees=0,
            ),
            PositionRecord(
                bucket="leaps",
                symbol="QQQ",
                asset_type="option",
                direction="long",
                option_type="call",
                quantity=3,
                multiplier=100,
                entry_price=100,
                current_price=95,
                opened_on=date(2026, 7, 29),
                expiration=date(2028, 7, 28),
                strike=400,
                tranche=1,
                entry_fees=0,
            ),
        ]
    )
    round_record = WheelRound(
        number=1, opened_on=date(2026, 7, 29), status="active", realized_profit=0
    )
    session.add(round_record)
    session.flush()
    session.add_all(
        [
            WheelPutLot(
                round_id=round_record.id,
                batch_number=1,
                trade_date=date(2026, 7, 15),
                expiration=date(2026, 8, 14),
                strike=66,
                premium=3.45,
                quantity=15,
                open_quantity=15,
                assigned_contracts=0,
                entry_tqqq_price=70,
                state="open",
                realized_profit=0,
            ),
            WheelPutLot(
                round_id=round_record.id,
                batch_number=2,
                trade_date=date(2026, 7, 22),
                expiration=date(2026, 8, 28),
                strike=55,
                premium=2.6,
                quantity=10,
                open_quantity=10,
                assigned_contracts=0,
                entry_tqqq_price=66,
                state="open",
                realized_profit=0,
            ),
        ]
    )
    session.commit()


def test_snapshot_derives_strategy_commitments_and_cash_capacity() -> None:
    with make_session() as session:
        seed_capital(session)

        snapshot = CapitalAccountingService(session).snapshot()

        assert snapshot.core.committed == Decimal("37520.00")
        assert snapshot.core.available == Decimal("130480.00")
        assert snapshot.wheel.committed == Decimal("154000.00")
        assert snapshot.wheel.cash_occupancy == Decimal("72400.00")
        assert snapshot.leaps.committed == Decimal("30000.00")
        assert snapshot.leaps.cash_occupancy == Decimal("9600.00")
        assert snapshot.options.assigned == Decimal("102000.00")
        assert snapshot.options.committed == Decimal("184000.00")
        assert snapshot.options.cash_occupancy == Decimal("82000.00")
        assert snapshot.cash.occupied == Decimal("82000.00")
        assert snapshot.cash.margin_shortfall == Decimal("52000.00")


def test_deployments_use_market_value_for_long_positions_and_collateral_for_wheel() -> None:
    with make_session() as session:
        seed_capital(session)

        deployments = CapitalAccountingService(session).deployments()

        assert deployments == {
            "core": Decimal("40989.60"),
            "cash": Decimal("30000.00"),
            "wheel": Decimal("154000.00"),
            "leaps": Decimal("28500.00"),
            "options": Decimal("182500.00"),
        }


def test_one_option_strategy_can_exceed_its_legacy_bucket_without_using_cash() -> None:
    with make_session() as session:
        session.add_all(
            [
                BucketBalance(bucket="wheel", amount=Decimal("14000")),
                BucketBalance(bucket="leaps", amount=Decimal("25000")),
                BucketBalance(bucket="cash", amount=Decimal("5000")),
            ]
        )
        round_record = WheelRound(
            number=1,
            opened_on=date(2026, 8, 1),
            status="active",
            realized_profit=0,
        )
        session.add(round_record)
        session.flush()
        session.add(
            WheelPutLot(
                round_id=round_record.id,
                batch_number=1,
                trade_date=date(2026, 8, 1),
                expiration=date(2026, 9, 4),
                strike=Decimal("100"),
                premium=Decimal("2"),
                quantity=3,
                open_quantity=3,
                assigned_contracts=0,
                entry_tqqq_price=Decimal("110"),
                state="open",
                realized_profit=0,
            )
        )
        session.commit()

        snapshot = CapitalAccountingService(session).snapshot()

        assert snapshot.wheel.cash_occupancy == Decimal("16000.00")
        assert snapshot.options.committed == Decimal("30000.00")
        assert snapshot.options.available == Decimal("9000.00")
        assert snapshot.options.cash_occupancy == Decimal("0.00")
        assert snapshot.cash.occupied == Decimal("0.00")
        assert snapshot.cash.margin_shortfall == Decimal("0.00")


def test_cash_transfer_cannot_spend_temporarily_occupied_cash() -> None:
    with make_session() as session:
        seed_capital(session, cash=Decimal("100000"))

        with pytest.raises(ValueError, match="可用现金不足"):
            PortfolioStore(session).transfer(
                Bucket.CASH,
                Bucket.CORE,
                Decimal("20000"),
                date(2026, 7, 29),
            )


def test_realized_loss_uses_strategy_then_cash_and_reversal_restores_both() -> None:
    with make_session() as session:
        session.add_all(
            [
                BucketBalance(bucket="wheel", amount=Decimal("4000")),
                BucketBalance(bucket="cash", amount=Decimal("3000")),
            ]
        )
        session.commit()
        service = RealizedCashService(session)

        service.post(
            "wheel-test-loss",
            Bucket.WHEEL,
            Decimal("-6500"),
            date(2026, 7, 29),
        )
        session.commit()

        assert session.get(BucketBalance, "wheel").amount == Decimal("0")
        assert session.get(BucketBalance, "cash").amount == Decimal("500")

        assert service.reverse(
            "wheel-test-loss", date(2026, 7, 30), "测试冲销"
        ) is True
        session.commit()
        assert session.get(BucketBalance, "wheel").amount == Decimal("4000")
        assert session.get(BucketBalance, "cash").amount == Decimal("3000")


def test_option_loss_uses_shared_pool_before_cash_and_reversal_restores_it() -> None:
    with make_session() as session:
        session.add_all(
            [
                BucketBalance(bucket="wheel", amount=Decimal("1000")),
                BucketBalance(bucket="leaps", amount=Decimal("4000")),
                BucketBalance(bucket="cash", amount=Decimal("5000")),
            ]
        )
        session.commit()
        service = RealizedCashService(session)

        service.post(
            "wheel-shared-pool-loss",
            Bucket.WHEEL,
            Decimal("-3000"),
            date(2026, 8, 26),
        )
        session.commit()

        assert session.get(BucketBalance, "wheel").amount == Decimal("0")
        assert session.get(BucketBalance, "leaps").amount == Decimal("2000")
        assert session.get(BucketBalance, "cash").amount == Decimal("5000")

        assert service.reverse(
            "wheel-shared-pool-loss", date(2026, 8, 27), "测试共享池冲销"
        ) is True
        session.commit()
        assert session.get(BucketBalance, "wheel").amount == Decimal("1000")
        assert session.get(BucketBalance, "leaps").amount == Decimal("4000")
        assert session.get(BucketBalance, "cash").amount == Decimal("5000")


def test_profit_allocation_cannot_spend_occupied_cash() -> None:
    with make_session() as session:
        seed_capital(session, cash=Decimal("100000"))
        session.add(
            ProfitLedgerEntry(
                entry_type="realized",
                source="leaps",
                amount=Decimal("50000"),
                occurred_on=date(2026, 7, 29),
                note="测试收益",
                details={},
            )
        )
        session.commit()

        with pytest.raises(ValueError, match="可用现金不足"):
            ProfitLedgerService(session).record_allocation(
                date(2026, 7, 29),
                Decimal("20000"),
                {Bucket.CORE: Decimal("20000")},
            )
