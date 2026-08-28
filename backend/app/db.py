import os
from pathlib import Path

from decimal import Decimal

from sqlalchemy import Engine, create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.db_models import (
    Base,
    BucketBalance,
    LedgerEvent,
    OtherHoldingRecord,
    PortfolioProfile,
    UnmanagedPositionRecord,
)
from app.domain.models import Bucket
from app.domain.redistribution import recommend_distribution

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "wheeldesk.db"


def create_database_engine(path: Path | None = None) -> Engine:
    selected = path or Path(os.getenv("WHEELDESK_DB_PATH", DEFAULT_DB_PATH))
    selected.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite+pysqlite:///{selected}",
        connect_args={"check_same_thread": False},
    )


engine = create_database_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False, class_=Session)


def initialize_database(selected_engine: Engine = engine) -> None:
    Base.metadata.create_all(selected_engine)
    exit_position_columns = {
        column["name"]
        for column in inspect(selected_engine).get_columns("exit_positions")
    }
    if "cost_price" not in exit_position_columns:
        with selected_engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE exit_positions ADD COLUMN cost_price NUMERIC(18, 2)"
            )
    profile_columns = {
        column["name"]
        for column in inspect(selected_engine).get_columns("portfolio_profile")
    }
    if "other_holdings_value" not in profile_columns:
        with selected_engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE portfolio_profile "
                "ADD COLUMN other_holdings_value NUMERIC(18, 2) NOT NULL DEFAULT 0"
            )
    if "last_rebalanced_on" not in profile_columns:
        with selected_engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE portfolio_profile ADD COLUMN last_rebalanced_on DATE"
            )
    position_columns = {
        column["name"] for column in inspect(selected_engine).get_columns("positions")
    }
    additions = {
        "rolled_from_position_id": "INTEGER REFERENCES positions(id)",
        "quote_source": "VARCHAR(30)",
        "quote_bid": "NUMERIC(18, 4)",
        "quote_ask": "NUMERIC(18, 4)",
        "quote_last": "NUMERIC(18, 4)",
        "quote_iv": "NUMERIC(12, 6)",
        "quote_as_of": "DATETIME",
        "peak_bid": "NUMERIC(18, 4)",
        "underlying_entry_price": "NUMERIC(18, 4)",
    }
    for name, sql_type in additions.items():
        if name not in position_columns:
            with selected_engine.begin() as connection:
                connection.exec_driver_sql(
                    f"ALTER TABLE positions ADD COLUMN {name} {sql_type}"
                )
    wheel_put_columns = {
        column["name"] for column in inspect(selected_engine).get_columns("wheel_put_lots")
    }
    wheel_put_additions = {
        "symbol": "VARCHAR(20) NOT NULL DEFAULT 'TQQQ'",
        "earnings_confirmed": "BOOLEAN NOT NULL DEFAULT 0",
        "rolled_from_put_id": "INTEGER REFERENCES wheel_put_lots(id)",
    }
    for name, sql_type in wheel_put_additions.items():
        if name not in wheel_put_columns:
            with selected_engine.begin() as connection:
                connection.exec_driver_sql(
                    f"ALTER TABLE wheel_put_lots ADD COLUMN {name} {sql_type}"
                )
    _migrate_legacy_unallocated(selected_engine)
    _migrate_legacy_other_holdings(selected_engine)


def _migrate_legacy_unallocated(selected_engine: Engine) -> None:
    with Session(selected_engine) as session:
        profile = session.get(PortfolioProfile, 1)
        unallocated = session.get(BucketBalance, Bucket.UNALLOCATED.value)
        if profile is None or unallocated is None or unallocated.amount <= 0:
            return
        migrated = session.scalar(
            select(LedgerEvent.id).where(
                LedgerEvent.event_type == "legacy_unallocated_migration"
            )
        )
        if migrated is not None:
            return
        balances = {bucket: Decimal("0") for bucket in Bucket}
        for row in session.scalars(select(BucketBalance)):
            balances[Bucket(row.bucket)] = row.amount
        total = sum(balances.values(), Decimal("0"))
        recommendation = recommend_distribution(
            unallocated.amount, total, profile.age, balances
        )
        for bucket, amount in recommendation.allocations.items():
            if amount <= 0:
                continue
            row = session.get(BucketBalance, bucket.value)
            if row is None:
                row = BucketBalance(bucket=bucket.value, amount=Decimal("0"))
                session.add(row)
            row.amount += amount
        distributed = unallocated.amount - recommendation.unallocated
        unallocated.amount = recommendation.unallocated
        session.add(
            LedgerEvent(
                event_type="legacy_unallocated_migration",
                bucket=Bucket.UNALLOCATED.value,
                amount=-distributed,
                occurred_on=profile.opening_date,
                details={
                    "allocations": {
                        bucket.value: float(amount)
                        for bucket, amount in recommendation.allocations.items()
                        if amount > 0
                    }
                },
            )
        )
        session.commit()


def _migrate_legacy_other_holdings(selected_engine: Engine) -> None:
    with Session(selected_engine) as session:
        existing_legacy_ids = set(
            session.scalars(
                select(UnmanagedPositionRecord.legacy_other_holding_id).where(
                    UnmanagedPositionRecord.legacy_other_holding_id.is_not(None)
                )
            )
        )
        records = list(session.scalars(select(OtherHoldingRecord)))
        for record in records:
            if record.id in existing_legacy_ids:
                continue
            session.add(
                UnmanagedPositionRecord(
                    category=("cash_equivalent" if record.symbol.upper() == "BOXX" else "other"),
                    symbol=record.symbol.upper(),
                    asset_type="equity",
                    direction="long",
                    quantity=record.quantity,
                    multiplier=1,
                    current_price=record.current_price,
                    quote_source=record.quote_source,
                    quote_as_of=record.quote_as_of,
                    last_error=record.last_error,
                    legacy_other_holding_id=record.id,
                )
            )
        if records:
            session.commit()


def get_session():
    with SessionLocal() as session:
        yield session
