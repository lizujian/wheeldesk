import os
from pathlib import Path

from decimal import Decimal

from sqlalchemy import Engine, create_engine, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.db_models import (
    Base,
    BrokerImportRecord,
    BucketBalance,
    LedgerEvent,
    OtherHoldingRecord,
    PortfolioProfile,
    UnmanagedPositionRecord,
    PositionRecord,
    WheelPutLot,
    WheelRound,
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
    unmanaged_columns = {
        column["name"]
        for column in inspect(selected_engine).get_columns("unmanaged_positions")
    }
    if "linked_position_id" not in unmanaged_columns:
        with selected_engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE unmanaged_positions "
                "ADD COLUMN linked_position_id INTEGER REFERENCES positions(id)"
            )
    wheel_put_columns = {
        column["name"] for column in inspect(selected_engine).get_columns("wheel_put_lots")
    }
    wheel_put_additions = {
        "symbol": "VARCHAR(20) NOT NULL DEFAULT 'TQQQ'",
        "capital_bucket": "VARCHAR(20) NOT NULL DEFAULT 'wheel'",
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
    _migrate_strategy_positions(selected_engine)


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


def _migrate_strategy_positions(selected_engine: Engine) -> None:
    """Reclassify already imported strategy legs after the taxonomy changed."""
    from app.domain.core import CORE_PUT_SYMBOLS
    from app.domain.leaps import LEAPS_CALL_WHEEL_CATEGORY

    with Session(selected_engine) as session:
        changed = False
        strategy_calls = list(
            session.scalars(
                select(UnmanagedPositionRecord).where(
                    UnmanagedPositionRecord.asset_type == "option",
                    UnmanagedPositionRecord.direction == "short",
                    UnmanagedPositionRecord.option_type == "call",
                    UnmanagedPositionRecord.category == "other",
                )
            )
        )
        allocated: dict[int, Decimal] = {}
        existing_pmcc_calls = session.scalars(
            select(UnmanagedPositionRecord).where(
                UnmanagedPositionRecord.status == "open",
                UnmanagedPositionRecord.category.in_({"pmcc", "leaps_call_wheel"}),
                UnmanagedPositionRecord.linked_position_id.is_not(None),
            )
        )
        for call in existing_pmcc_calls:
            assert call.linked_position_id is not None
            allocated[call.linked_position_id] = (
                allocated.get(call.linked_position_id, Decimal("0")) + call.quantity
            )
        for record in strategy_calls:
            if record.symbol == "QLD":
                # A QLD replacement position covers one call with 100 shares.
                required_quantity = record.quantity * Decimal("100")
                candidates = list(
                    session.scalars(
                        select(PositionRecord).where(
                            PositionRecord.status == "open",
                            PositionRecord.bucket == "leaps",
                            PositionRecord.asset_type == "equity",
                            PositionRecord.direction == "long",
                            PositionRecord.option_type.is_(None),
                            PositionRecord.symbol == "QLD",
                            PositionRecord.quantity >= required_quantity,
                        )
                    )
                )
            else:
                candidates = list(
                    session.scalars(
                        select(PositionRecord).where(
                            PositionRecord.status == "open",
                            PositionRecord.bucket == "leaps",
                            PositionRecord.asset_type == "option",
                            PositionRecord.direction == "long",
                            PositionRecord.option_type == "call",
                            PositionRecord.symbol == record.symbol,
                            PositionRecord.quantity >= record.quantity,
                        )
                    )
                )
            candidates = sorted(
                candidates,
                key=lambda candidate: (candidate.opened_on, candidate.id),
            )
            required_quantity = (
                record.quantity * Decimal("100")
                if record.symbol == "QLD"
                else record.quantity
            )
            candidate = next(
                (
                    position
                    for position in candidates
                    if position.quantity
                    - allocated.get(position.id, Decimal("0"))
                    >= required_quantity
                ),
                None,
            )
            if candidate is None:
                continue
            record.category = LEAPS_CALL_WHEEL_CATEGORY
            record.linked_position_id = candidate.id
            allocated[candidate.id] = (
                allocated.get(candidate.id, Decimal("0")) + required_quantity
            )
            _update_import_entity(
                session,
                record.id,
                entity_type="leaps_call_wheel",
                entity_id=record.id,
            )
            changed = True

        core_puts = list(
            session.scalars(
                select(UnmanagedPositionRecord).where(
                    UnmanagedPositionRecord.status == "open",
                    UnmanagedPositionRecord.asset_type == "option",
                    UnmanagedPositionRecord.direction == "short",
                    UnmanagedPositionRecord.option_type == "put",
                    UnmanagedPositionRecord.symbol.in_(CORE_PUT_SYMBOLS),
                    UnmanagedPositionRecord.category == "other",
                )
            )
        )
        for record in core_puts:
            if record.expiration is None or record.strike is None:
                continue
            duplicate = session.scalar(
                select(WheelPutLot.id).where(
                    WheelPutLot.state == "open",
                    WheelPutLot.capital_bucket == "core",
                    WheelPutLot.symbol == record.symbol,
                    WheelPutLot.expiration == record.expiration,
                    WheelPutLot.strike == record.strike,
                )
            )
            if duplicate is not None:
                continue
            round_number = int(
                session.scalar(select(func.coalesce(func.max(WheelRound.number), 0))) or 0
            ) + 1
            trade_date = record.opened_on or date.today()
            round_record = WheelRound(
                number=round_number,
                opened_on=trade_date,
                status="active",
            )
            session.add(round_record)
            session.flush()
            put = WheelPutLot(
                round_id=round_record.id,
                symbol=record.symbol,
                capital_bucket="core",
                batch_number=1,
                trade_date=trade_date,
                expiration=record.expiration,
                strike=record.strike,
                premium=record.entry_price or Decimal("0.01"),
                quantity=int(record.quantity),
                open_quantity=int(record.quantity),
                assigned_contracts=0,
                entry_tqqq_price=Decimal("0"),
                earnings_confirmed=True,
                state="open",
                realized_profit=Decimal("0"),
            )
            session.add(put)
            session.flush()
            _update_import_entity(
                session,
                record.id,
                entity_type="wheel_put",
                entity_id=put.id,
            )
            session.delete(record)
            changed = True

        if changed:
            session.commit()


def _update_import_entity(
    session: Session,
    unmanaged_id: int,
    *,
    entity_type: str,
    entity_id: int,
) -> None:
    rows = session.scalars(
        select(BrokerImportRecord).where(
            BrokerImportRecord.entity_type == "unmanaged_position",
            BrokerImportRecord.entity_id == unmanaged_id,
        )
    )
    for row in rows:
        row.entity_type = entity_type
        row.entity_id = entity_id


def get_session():
    with SessionLocal() as session:
        yield session
