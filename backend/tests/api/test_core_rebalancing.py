from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db_models import Base, BucketBalance, LedgerEvent, PositionRecord
from app.services.core_rebalancing import CoreRebalancingService
from app.services.portfolio_store import PortfolioStore


def make_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    PortfolioStore(session).initialize(30, Decimal("100000"), date(2026, 1, 1))
    return session


def add_lot(session: Session, opened_on: date, quantity: int, price: int) -> None:
    session.add(
        PositionRecord(
            bucket="core",
            symbol="BRK.B",
            asset_type="equity",
            direction="long",
            quantity=quantity,
            multiplier=1,
            entry_price=price,
            current_price=price,
            opened_on=opened_on,
            entry_fees=0,
        )
    )
    session.commit()


def test_fifo_rebalance_sale_can_span_lots_and_moves_actual_proceeds_to_cash() -> None:
    with make_session() as session:
        add_lot(session, date(2026, 1, 10), 10, 100)
        add_lot(session, date(2026, 2, 10), 10, 200)

        result = CoreRebalancingService(session).sell_fifo(
            date(2026, 7, 31), Decimal("15"), Decimal("300")
        )

        assert result["quantity"] == Decimal("15.0000")
        assert result["cost_basis"] == Decimal("2000.00")
        assert result["proceeds"] == Decimal("4500.00")
        assert result["realized_profit"] == Decimal("2500.00")
        lots = list(
            session.scalars(
                select(PositionRecord).order_by(
                    PositionRecord.opened_on, PositionRecord.id
                )
            )
        )
        assert lots[0].status == "closed"
        assert lots[0].quantity == 0
        assert lots[1].status == "open"
        assert lots[1].quantity == Decimal("5")
        assert session.get(BucketBalance, "core").amount == Decimal("68000")
        assert session.get(BucketBalance, "cash").amount == Decimal("9500")
        assert PortfolioStore(session).profile().last_rebalanced_on == date(2026, 7, 31)
        event = session.scalar(
            select(LedgerEvent).where(LedgerEvent.event_type == "core_rebalance_sale")
        )
        assert event.details["cost_basis"] == 2000.0
        assert event.details["proceeds"] == 4500.0
