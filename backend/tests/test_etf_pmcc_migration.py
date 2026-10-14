from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import create_database_engine, initialize_database
from app.db_models import Base, BrokerImportRecord, BucketBalance, LedgerEvent, PositionRecord, UnmanagedPositionRecord
from app.services.pmcc import pmcc_snapshot


@pytest.mark.parametrize('symbol', ['DRAM', 'SOXX'])
def test_existing_etf_pmcc_moves_once_with_cost_quotes_and_import_links_preserved(tmp_path, symbol):
    engine = create_database_engine(tmp_path / f'{symbol}.db')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(BucketBalance(bucket='leaps', amount=25000))
        long = UnmanagedPositionRecord(
            category='other', symbol=symbol, asset_type='option', direction='long', option_type='call',
            quantity=1, multiplier=100, entry_price=Decimal('10.68'), current_price=Decimal('10.65'),
            opened_on=date(2026, 10, 13), expiration=date(2027, 6, 17), strike=50,
            quote_source='ibkr', quote_as_of=date(2026, 10, 14), quote_vendor='ibkr', quote_quality='closed',
            quote_fetched_at=datetime(2026, 10, 14, 10, tzinfo=timezone.utc),
        )
        short = UnmanagedPositionRecord(
            category='other', symbol=symbol, asset_type='option', direction='short', option_type='call',
            quantity=1, multiplier=100, entry_price=Decimal('1.52'), current_price=Decimal('1.88'),
            opened_on=date(2026, 10, 13), expiration=date(2026, 10, 30), strike=55,
        )
        old_wheel_call = UnmanagedPositionRecord(
            category='other', symbol=symbol, asset_type='option', direction='short', option_type='call',
            quantity=1, multiplier=100, entry_price=2, current_price=1, opened_on=date(2026, 8, 11),
            expiration=date(2026, 8, 28), strike=55, status='closed', closed_on=date(2026, 8, 28),
            exit_price=1, realized_profit=100,
        )
        session.add_all([long, short, old_wheel_call])
        session.flush()
        old_long_id, short_id, wheel_id = long.id, short.id, old_wheel_call.id
        for index, record in enumerate([long, short]):
            session.add(BrokerImportRecord(fingerprint=str(index) * 64, filename='etf.csv', section='Open Positions',
                row_index=index, action='create_unmanaged', entity_type='unmanaged_position', entity_id=record.id))
        session.commit()

    for _ in range(2):
        initialize_database(engine)
        with Session(engine) as session:
            longs = list(session.scalars(select(PositionRecord).where(PositionRecord.symbol == symbol)))
            assert len(longs) == 1, 'ETF Long Call must move into LEAPS management'
            position = longs[0]
            assert position.bucket == 'leaps' and position.tranche == 1
            assert (position.entry_price, position.current_price, position.quantity) == (Decimal('10.68'), Decimal('10.65'), 1)
            assert position.opened_on == date(2026, 10, 13) and position.expiration == date(2027, 6, 17)
            assert position.quote_vendor == 'ibkr' and position.quote_quality == 'closed'
            assert position.quote_fetched_at == datetime(2026, 10, 14, 10)
            assert session.get(UnmanagedPositionRecord, old_long_id) is None
            call = session.get(UnmanagedPositionRecord, short_id)
            assert call.category == 'leaps_call_wheel' and call.linked_position_id == position.id
            assert (call.entry_price, call.current_price, call.quantity) == (Decimal('1.52'), Decimal('1.88'), 1)
            old_call = session.get(UnmanagedPositionRecord, wheel_id)
            assert old_call.category == 'other' and old_call.linked_position_id is None and old_call.realized_profit == 100
            imports = list(session.scalars(select(BrokerImportRecord).order_by(BrokerImportRecord.id)))
            assert (imports[0].entity_type, imports[0].entity_id) == ('position', position.id)
            assert (imports[1].entity_type, imports[1].entity_id) == ('leaps_call_wheel', short_id)
            assert session.get(BucketBalance, 'leaps').amount == 25000
            assert sum(event.amount for event in session.scalars(select(LedgerEvent))) == 0
            pmcc = pmcc_snapshot(session, as_of=date(2026, 10, 14))
            assert pmcc['total']['committed'] == 1068
            assert pmcc['states'][0]['coverage_ratio'] == 1
