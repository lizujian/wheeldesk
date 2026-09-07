from datetime import date, timedelta
from decimal import Decimal as D

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import Base, CoreTradeRecord, PositionRecord
from app.services.portfolio_store import PortfolioStore
from app.services.core_rotation import CoreRotationService
from app.services.ibkr_import import IbkrImportService, parse_activity_statement


REPORT = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"September 4, 2026"
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,Code
Trades,Data,Order,Stocks,USD,BRK B,"2026-09-04, 10:00:00",-20,400,C
Trades,Data,Order,Stocks,USD,VOO,"2026-09-04, 10:01:00",16,500,O
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Close Price
Open Positions,Data,Summary,Stocks,USD,BRK B,80,1,390,400
Open Positions,Data,Summary,Stocks,USD,VOO,16,1,500,500
'''


def prices(end=date(2026, 9, 4)):
    days = [end - timedelta(days=offset) for offset in range(50) if (end - timedelta(days=offset)).weekday() < 5]
    return {"BRK.B": {day: D("400") for day in days}, "VOO": {day: D("500") for day in days}}


def test_daily_and_range_reimports_count_actual_sell_once_not_both_legs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        importer = IbkrImportService(session)
        importer._record_core_trades(parse_activity_statement(REPORT))
        importer._record_core_trades(parse_activity_statement(REPORT.replace('September 4, 2026', 'September 1, 2026 - September 4, 2026')))
        rows = list(session.scalars(select(CoreTradeRecord)))
        assert len(rows) == 2
        sale = next(row for row in rows if row.quantity < 0)
        assert sale.pre_quantities == {"BRK.B": "100", "VOO": "0"}
        usage, executions = CoreRotationService(session).usage(prices())
        assert usage.complete
        assert usage.used_weight == D(".20")
        assert len(executions) == 1
        assert executions[0]["proceeds"] == D("8000")
        assert CoreRotationService(session).usage(prices(date(2026, 10, 2)))[0].used_weight == 0


def test_missing_snapshot_pauses_rotation_until_later_report_supplies_it():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        importer = IbkrImportService(session)
        importer._record_core_trades(parse_activity_statement(REPORT.split('Open Positions,Header')[0]))
        assert not CoreRotationService(session).usage(prices())[0].complete
        importer._record_core_trades(parse_activity_statement(REPORT))
        usage, _ = CoreRotationService(session).usage(prices())
        assert usage.complete
        assert usage.used_weight == D(".20")


def test_partial_sales_are_accumulated_and_snapshot_only_does_not_create_a_fill():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        importer = IbkrImportService(session)
        importer._record_core_trades(parse_activity_statement(REPORT))
        next_report = REPORT.replace('September 4, 2026', 'September 7, 2026').replace('2026-09-04', '2026-09-07').replace(',-20,400', ',-5,400').replace(',16,500,O', ',4,500,O').replace('BRK B,80,', 'BRK B,75,').replace('VOO,16,', 'VOO,20,')
        importer._record_core_trades(parse_activity_statement(next_report))
        usage, executions = CoreRotationService(session).usage(prices(date(2026, 9, 7)))
        assert usage.used_weight == D(".25")
        assert len(executions) == 2
        importer._record_core_trades(parse_activity_statement(next_report[next_report.index('Open Positions,Header'):]))
        assert len(list(session.scalars(select(CoreTradeRecord)))) == 4


def test_full_voo_sale_closes_absent_snapshot_once_and_preserves_later_holdings():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    report = REPORT.replace('BRK B,"2026-09-04, 10:00:00",-20,400,C', 'VOO,"2026-09-04, 10:00:00",-20,500,C').replace('VOO,"2026-09-04, 10:01:00",16,500,O', 'BRK B,"2026-09-04, 10:01:00",25,400,O').replace('BRK B,80,', 'BRK B,25,').replace('Open Positions,Data,Summary,Stocks,USD,VOO,16,1,500,500\n', '')
    with Session(engine) as session:
        PortfolioStore(session).initialize(36, D("100000"), date(2026, 1, 1))
        old = PositionRecord(bucket="core", symbol="VOO", asset_type="equity", direction="long", quantity=20, multiplier=1, entry_price=490, current_price=500, opened_on=date(2026, 8, 1), entry_fees=0)
        session.add(old)
        session.commit()
        importer = IbkrImportService(session)
        importer._record_core_trades(parse_activity_statement(report))
        assert old.status == "closed"
        assert old.quantity == 0
        assert old.realized_profit == D("200")
        newer = PositionRecord(bucket="core", symbol="VOO", asset_type="equity", direction="long", quantity=10, multiplier=1, entry_price=490, current_price=500, opened_on=date(2026, 9, 7), entry_fees=0)
        session.add(newer)
        session.commit()
        importer._record_core_trades(parse_activity_statement(report))
        assert newer.status == "open"
        assert newer.quantity == 10
