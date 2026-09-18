from datetime import date
from pathlib import Path

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.db import create_database_engine, initialize_database
from app.db_models import (
    Base,
    BrokerImportRecord,
    BucketBalance,
    OtherHoldingRecord,
    PortfolioProfile,
    PositionRecord,
    UnmanagedPositionRecord,
    WheelPutLot,
    WheelRound,
)


def test_initialize_database_adds_cost_price_without_losing_exit_records(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "legacy.db")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE exit_positions (
                id INTEGER PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                position_type VARCHAR(20) NOT NULL,
                current_value NUMERIC(18, 2) NOT NULL,
                target_value NUMERIC(18, 2) NOT NULL,
                note VARCHAR(500) NOT NULL DEFAULT '',
                status VARCHAR(12) NOT NULL DEFAULT 'active',
                recovered_cash NUMERIC(18, 2) NOT NULL DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO exit_positions "
            "(id, name, position_type, current_value, target_value) "
            "VALUES (1, 'Legacy stock', 'stock', 5000, 8000)"
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE portfolio_profile (
                id INTEGER PRIMARY KEY,
                age INTEGER NOT NULL,
                opening_equity NUMERIC(18, 2) NOT NULL,
                opening_date DATE NOT NULL,
                currency VARCHAR(3) NOT NULL DEFAULT 'USD'
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO portfolio_profile "
            "(id, age, opening_equity, opening_date, currency) "
            "VALUES (1, 36, 179726, '2026-07-10', 'USD')"
        )

    initialize_database(engine)
    initialize_database(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("exit_positions")}
    profile_columns = {
        column["name"] for column in inspect(engine).get_columns("portfolio_profile")
    }
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT name, cost_price FROM exit_positions WHERE id = 1"
        ).one()
        profile = connection.exec_driver_sql(
            "SELECT age, opening_equity, other_holdings_value "
            "FROM portfolio_profile WHERE id = 1"
        ).one()

    assert "cost_price" in columns
    assert row == ("Legacy stock", None)
    assert "other_holdings_value" in profile_columns
    assert profile == (36, 179726, 0)


def test_initialize_database_adds_quote_fields_without_losing_positions(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "legacy-positions.db")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY,
                bucket VARCHAR(30) NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                asset_type VARCHAR(20) NOT NULL,
                direction VARCHAR(10) NOT NULL DEFAULT 'long',
                option_type VARCHAR(10),
                quantity NUMERIC(18, 4) NOT NULL,
                multiplier INTEGER NOT NULL DEFAULT 1,
                entry_price NUMERIC(18, 4) NOT NULL,
                current_price NUMERIC(18, 4) NOT NULL,
                opened_on DATE NOT NULL,
                expiration DATE,
                strike NUMERIC(18, 2),
                delta NUMERIC(8, 4),
                tranche INTEGER,
                entry_fees NUMERIC(18, 2) NOT NULL DEFAULT 0,
                status VARCHAR(12) NOT NULL DEFAULT 'open',
                closed_on DATE,
                exit_price NUMERIC(18, 4),
                exit_fees NUMERIC(18, 2) NOT NULL DEFAULT 0,
                realized_profit NUMERIC(18, 2)
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO positions (
                id, bucket, symbol, asset_type, direction, option_type,
                quantity, multiplier, entry_price, current_price, opened_on,
                expiration, strike, tranche
            ) VALUES (
                7, 'leaps', 'QQQ', 'option', 'long', 'call',
                2, 100, 100, 105, '2026-07-10', '2028-07-21', 500, 1
            )
            """
        )

    initialize_database(engine)
    initialize_database(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("positions")}
    quote_columns = {
        "rolled_from_position_id",
        "quote_source",
        "quote_bid",
        "quote_ask",
        "quote_last",
        "quote_iv",
        "quote_as_of",
        "peak_bid",
        "underlying_entry_price",
    }
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT id, bucket, symbol, quantity, entry_price, tranche "
            "FROM positions WHERE id = 7"
        ).one()

    assert quote_columns <= columns
    assert row == (7, "leaps", "QQQ", 2, 100, 1)


def test_initialize_database_marks_legacy_wheel_puts_as_tqqq(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "legacy-wheel.db")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE wheel_put_lots (
                id INTEGER PRIMARY KEY,
                round_id INTEGER NOT NULL,
                batch_number INTEGER NOT NULL,
                trade_date DATE NOT NULL,
                expiration DATE NOT NULL,
                strike NUMERIC(18, 2) NOT NULL,
                premium NUMERIC(18, 4) NOT NULL,
                quantity INTEGER NOT NULL,
                open_quantity INTEGER NOT NULL,
                assigned_contracts INTEGER NOT NULL DEFAULT 0,
                entry_tqqq_price NUMERIC(18, 4) NOT NULL,
                state VARCHAR(20) NOT NULL DEFAULT 'open',
                realized_profit NUMERIC(18, 2) NOT NULL DEFAULT 0
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO wheel_put_lots "
            "(id, round_id, batch_number, trade_date, expiration, strike, premium, "
            "quantity, open_quantity, entry_tqqq_price) "
            "VALUES (3, 2, 1, '2026-08-24', '2026-10-02', 55, 1.68, 5, 5, 68.1)"
        )

    initialize_database(engine)
    initialize_database(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("wheel_put_lots")}
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT symbol, earnings_confirmed, capital_bucket "
            "FROM wheel_put_lots WHERE id = 3"
        ).one()

    assert {"symbol", "earnings_confirmed", "rolled_from_put_id", "capital_bucket"} <= columns
    assert row == ("TQQQ", 0, "wheel")


def test_initialize_database_migrates_legacy_other_holdings_once(tmp_path: Path) -> None:
    engine = create_database_engine(tmp_path / "legacy-other-holdings.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                OtherHoldingRecord(symbol="BOXX", quantity=200, current_price=100),
                OtherHoldingRecord(symbol="AAPL", quantity=10, current_price=250),
            ]
        )
        session.commit()

    initialize_database(engine)
    initialize_database(engine)

    with Session(engine) as session:
        records = list(session.query(UnmanagedPositionRecord).order_by(UnmanagedPositionRecord.symbol))
        assert len(records) == 2
        assert records[0].symbol == "AAPL"
        assert records[0].category == "other"
        assert records[1].symbol == "BOXX"
        assert records[1].category == "cash_equivalent"
        assert {record.legacy_other_holding_id for record in records} == {1, 2}


def test_initialize_database_reclassifies_existing_core_put_and_leaps_call(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "strategy-taxonomy.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            PositionRecord(
                bucket="leaps",
                symbol="GOOG",
                asset_type="option",
                direction="long",
                option_type="call",
                quantity=1,
                multiplier=100,
                entry_price=38.86,
                current_price=36.88,
                opened_on=date(2026, 8, 31),
                expiration=date(2027, 3, 19),
                strike=330,
                tranche=1,
                entry_fees=0,
            )
        )
        session.flush()
        session.add(
            PositionRecord(
                bucket="leaps",
                symbol="QLD",
                asset_type="equity",
                direction="long",
                option_type=None,
                quantity=100,
                multiplier=1,
                entry_price=79.36,
                current_price=89.55,
                opened_on=date(2026, 7, 29),
                tranche=1,
                entry_fees=0,
            )
        )
        session.flush()
        session.add_all(
            [
                UnmanagedPositionRecord(
                    category="other",
                    symbol="GOOG",
                    asset_type="option",
                    direction="short",
                    option_type="call",
                    quantity=1,
                    multiplier=100,
                    entry_price=3.5,
                    current_price=3.975,
                    opened_on=date(2026, 9, 14),
                    expiration=date(2026, 10, 2),
                    strike=360,
                ),
                UnmanagedPositionRecord(
                    category="other",
                    symbol="SPY",
                    asset_type="option",
                    direction="short",
                    option_type="put",
                    quantity=1,
                    multiplier=100,
                    entry_price=3.69,
                    current_price=3.11,
                    opened_on=date(2026, 9, 14),
                    expiration=date(2026, 10, 2),
                    strike=735,
                ),
                UnmanagedPositionRecord(
                    category="other",
                    symbol="QLD",
                    asset_type="option",
                    direction="short",
                    option_type="call",
                    quantity=1,
                    multiplier=100,
                    entry_price=3.3896,
                    current_price=1.65,
                    opened_on=date(2026, 8, 27),
                    expiration=date(2026, 9, 18),
                    strike=90,
                    status="closed",
                    closed_on=date(2026, 9, 1),
                    exit_price=1.65,
                    realized_profit=173.96,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                BrokerImportRecord(
                    fingerprint="g" * 64,
                    filename="goog.csv",
                    section="Open Positions",
                    row_index=1,
                    action="create_unmanaged",
                    entity_type="unmanaged_position",
                    entity_id=1,
                ),
                BrokerImportRecord(
                    fingerprint="s" * 64,
                    filename="spy.csv",
                    section="Open Positions",
                    row_index=1,
                    action="create_unmanaged",
                    entity_type="unmanaged_position",
                    entity_id=2,
                ),
                BrokerImportRecord(
                    fingerprint="q" * 64,
                    filename="qld.csv",
                    section="Open Positions",
                    row_index=1,
                    action="create_unmanaged",
                    entity_type="unmanaged_position",
                    entity_id=3,
                ),
            ]
        )
        session.commit()

    initialize_database(engine)
    initialize_database(engine)

    with Session(engine) as session:
        goog = session.scalar(
            select(UnmanagedPositionRecord).where(
                UnmanagedPositionRecord.symbol == "GOOG"
            )
        )
        puts = list(
            session.scalars(select(WheelPutLot).where(WheelPutLot.symbol == "SPY"))
        )
        qld = session.scalar(
            select(UnmanagedPositionRecord).where(
                UnmanagedPositionRecord.symbol == "QLD"
            )
        )
        imported = list(
            session.scalars(select(BrokerImportRecord).order_by(BrokerImportRecord.id))
        )

        assert goog is not None
        assert goog.category == "leaps_call_wheel"
        assert goog.linked_position_id == 1
        assert qld is not None
        assert qld.category == "leaps_call_wheel"
        assert qld.linked_position_id == 2
        assert qld.status == "closed"
        assert len(puts) == 1
        assert puts[0].capital_bucket == "core"
        assert puts[0].symbol == "SPY"
        assert session.scalar(select(func.count(UnmanagedPositionRecord.id))) == 2
        assert imported[0].entity_type == "leaps_call_wheel"
        assert imported[1].entity_type == "wheel_put"
        assert imported[2].entity_type == "leaps_call_wheel"


def test_initialize_database_distributes_legacy_unallocated_once_and_preserves_trades(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(tmp_path / "legacy-unallocated.db")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            PortfolioProfile(
                id=1,
                age=36,
                opening_equity=300000,
                opening_date=date(2026, 7, 29),
                currency="USD",
            )
        )
        session.add_all(
            [
                BucketBalance(bucket="core", amount=0),
                BucketBalance(bucket="cash", amount=0),
                BucketBalance(bucket="wheel", amount=0),
                BucketBalance(bucket="leaps", amount=0),
                BucketBalance(bucket="unallocated", amount=300000),
            ]
        )
        session.add(
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
            )
        )
        round_record = WheelRound(
            number=1,
            opened_on=date(2026, 7, 29),
            status="active",
            realized_profit=0,
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

    initialize_database(engine)
    initialize_database(engine)

    with engine.connect() as connection:
        balances = dict(
            connection.exec_driver_sql(
                "SELECT bucket, amount FROM bucket_balances"
            ).all()
        )
        position_count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM positions"
        ).scalar_one()
        put_count = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM wheel_put_lots"
        ).scalar_one()
        migration_events = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM ledger_events "
            "WHERE event_type = 'legacy_unallocated_migration'"
        ).scalar_one()
    profile_columns = {
        column["name"] for column in inspect(engine).get_columns("portfolio_profile")
    }

    assert balances == {
        "cash": 15000,
        "core": 168000,
            "leaps": 0,
        "unallocated": 0,
            "wheel": 117000,
    }
    assert position_count == 1
    assert put_count == 2
    assert migration_events == 1
    assert "last_rebalanced_on" in profile_columns
