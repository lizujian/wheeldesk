"""Synthetic regressions for the full-project review; never use the live account."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session, initialize_database
from app.db_models import Base, BrokerImportRecord, PositionRecord, UnmanagedPositionRecord, WheelPutLot
from app.main import app


@pytest.fixture
def account():
    engine = create_engine('sqlite+pysqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    def dependency():
        with sessions() as session:
            yield session
    app.dependency_overrides[get_session] = dependency
    client = TestClient(app, base_url='http://127.0.0.1')
    assert client.post('/api/portfolio/initialize', json={'age': 36, 'opening_equity': 100000, 'opening_date': '2026-08-01'}).status_code == 201
    try:
        yield client, sessions
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()


def statement(day='2026-08-25', quantity=10, price=500, *, nav=None, currency='USD', symbol='BRK B'):
    content = f'''Statement,Header,Field Name,Field Value
Statement,Data,Period,{day}
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Close Price
Open Positions,Data,Summary,Stocks,{currency},{symbol},{quantity},1,500,{price}
'''
    if nav is not None:
        content += 'Account Information,Header,Field Name,Field Value\nAccount Information,Data,Base Currency,USD\n'
        content += f'Change in NAV,Header,Field Name,Field Value\nChange in NAV,Data,Ending Value,{nav}\n'
    return content


def upload(client, content):
    return client.post('/api/imports/ibkr/auto', json={'filename': 'synthetic.csv', 'content': content})


@pytest.mark.parametrize('method,path', [('get', '/api/portfolio/summary'), ('post', '/api/system/reset')])
def test_untrusted_host_cannot_read_or_reset_account(account, method, path):
    client, _ = account
    kwargs = {'headers': {'host': 'attacker.example:8000'}}
    if method == 'post':
        kwargs['json'] = {'confirmation': 'RESET'}
    assert getattr(client, method)(path, **kwargs).status_code == 400
    assert client.get('/api/portfolio/summary').json()['initialized'] is True


@pytest.mark.parametrize('headers', [
    {'Origin': 'https://attacker.example'}, {'Origin': 'null'},
    {'Origin': 'http://127.0.0.1.attacker.example:5173'}, {'Sec-Fetch-Site': 'cross-site'},
])
def test_untrusted_browser_cannot_write_local_account(account, headers):
    client, _ = account
    assert client.post('/api/system/reset', headers=headers, json={'confirmation': 'RESET'}).status_code == 403
    assert client.get('/api/portfolio/summary').json()['initialized'] is True


def test_trusted_frontend_can_write(account):
    client, _ = account
    assert client.post('/api/system/reset', headers={'Origin': 'http://127.0.0.1:5173'}, json={'confirmation': 'RESET'}).status_code == 200


def test_core_put_migration_without_opening_date(tmp_path):
    engine = create_engine(f'sqlite+pysqlite:///{tmp_path / "synthetic.db"}')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(UnmanagedPositionRecord(category='other', symbol='BRK.B', asset_type='option', direction='short', option_type='put', quantity=1, multiplier=100, entry_price=3, current_price=2, opened_on=None, expiration=date(2027, 1, 15), strike=450, status='open'))
        session.commit()
    initialize_database(engine)
    initialize_database(engine)
    with Session(engine) as session:
        puts = list(session.scalars(select(WheelPutLot)))
        assert len(puts) == 1
        assert puts[0].trade_date == date.today()
    engine.dispose()


def test_older_snapshot_does_not_undo_newer_state_but_can_add_history(account):
    client, _ = account
    assert upload(client, statement()).status_code == 200
    assert upload(client, statement('2026-08-26', 20)).status_code == 200
    old = statement() + 'Deposits & Withdrawals,Header,Currency,Settle Date,Description,Amount\nDeposits & Withdrawals,Data,USD,2026-08-20,Historical synthetic deposit,100\n'
    response = upload(client, old)
    assert response.status_code == 200, response.text
    assert client.get('/api/positions').json()[0]['quantity'] == 20
    assert client.get('/api/portfolio/summary').json()['net_external_capital'] == 100100
    assert response.json()['needs_attention'] == 1


def test_newer_identical_snapshot_advances_date_independently_of_quote(account):
    client, sessions = account
    upload(client, statement())
    upload(client, statement('2026-08-27'))
    with sessions() as session:
        position = session.scalar(select(PositionRecord))
        position.quote_as_of = datetime(2026, 10, 1)
        session.commit()
    upload(client, statement('2026-08-26', 20))
    assert client.get('/api/positions').json()[0]['quantity'] == 10
    upload(client, statement('2026-08-28', 30))
    assert client.get('/api/positions').json()[0]['quantity'] == 30


def test_import_failure_rolls_back_records_fingerprints_and_balances(account):
    client, _ = account
    baseline = client.get('/api/portfolio/summary').json()
    content = statement(symbol='AAPL') + 'Open Positions,Data,Summary,Stocks,USD,BRK B,1000,1,500,500\n'
    response = upload(client, content)
    assert response.status_code == 409
    assert client.get('/api/other-holdings').json()['records'] == []
    assert client.get('/api/imports/ibkr/history').json() == []
    assert client.get('/api/portfolio/summary').json() == baseline
    retry = upload(client, content.replace('BRK B,1000', 'BRK B,10'))
    assert retry.status_code == 200, retry.text
    assert retry.json()['imported'] == 2


def test_failure_after_business_changes_rolls_back_everything(account, monkeypatch):
    from app.services.ibkr_import import IbkrImportService
    client, sessions = account
    def fail(*args, **kwargs):
        raise RuntimeError('synthetic reconciliation failure')
    monkeypatch.setattr(IbkrImportService, '_reconcile_account_summary', fail)
    with pytest.raises(RuntimeError, match='synthetic reconciliation'):
        upload(client, statement(nav=100000))
    with sessions() as session:
        assert list(session.scalars(select(PositionRecord))) == []
        assert list(session.scalars(select(BrokerImportRecord))) == []


def test_unrealized_gain_is_not_spendable_cash_or_counted_twice(account):
    client, _ = account
    assert upload(client, statement(price=600, nav=101000)).status_code == 200
    portfolio = client.get('/api/portfolio/summary').json()
    assert portfolio['balances']['cash'] == 5000
    assert portfolio['capital']['cash']['available'] == 5000
    assert portfolio['total_equity'] == 101000
    assert client.get('/api/rebalancing').json()['economic']['total'] == 101000


def test_summary_only_report_updates_nav_without_creating_cash_and_ignores_older(account):
    client, _ = account
    upload(client, statement(nav=100000))
    content = 'Statement,Header,Field Name,Field Value\nStatement,Data,Period,2026-08-26\nChange in NAV,Header,Field Name,Field Value\nChange in NAV,Data,Ending Value,110000\n'
    content += 'Account Information,Header,Field Name,Field Value\nAccount Information,Data,Base Currency,USD\n'
    response = upload(client, content)
    assert response.status_code == 200, response.text
    portfolio = client.get('/api/portfolio/summary').json()
    assert portfolio['total_equity'] == 110000
    assert portfolio['balances']['cash'] == 5000
    assert client.get('/api/rebalancing').json()['economic']['total'] == 110000
    upload(client, statement(nav=100000))
    assert client.get('/api/portfolio/summary').json()['total_equity'] == 110000


def test_unchanged_positions_still_sync_new_summary(account):
    client, _ = account
    upload(client, statement(nav=100000))
    response = upload(client, statement('2026-08-26', nav=110000))
    assert response.status_code == 200
    assert response.json()['imported'] == 0
    assert response.json()['account_summary_updated'] is True
    assert client.get('/api/portfolio/summary').json()['total_equity'] == 110000


def test_foreign_deposit_is_reported_for_review_not_added_as_dollars(account):
    client, _ = account
    content = 'Statement,Header,Field Name,Field Value\nStatement,Data,Period,2026-08-26\nDeposits & Withdrawals,Header,Currency,Settle Date,Description,Amount\nDeposits & Withdrawals,Data,HKD,2026-08-25,Synthetic deposit,7800\n'
    response = upload(client, content)
    assert response.status_code == 200, response.text
    assert response.json()['needs_attention'] == 1
    portfolio = client.get('/api/portfolio/summary').json()
    assert portfolio['total_equity'] == portfolio['net_external_capital'] == 100000


def test_foreign_position_is_not_valued_in_dollars(account):
    client, _ = account
    response = upload(client, statement(currency='HKD'))
    assert response.status_code == 200
    assert response.json()['needs_attention'] == 1
    assert client.get('/api/positions').json() == []


def test_negative_cash_is_visible_in_shortfall_and_rebalancing(account):
    client, _ = account
    response = client.post('/api/profit-ledger/realized', json={'source': 'leaps', 'occurred_on': '2026-08-25', 'amount': -40000})
    assert response.status_code == 201
    cash = client.get('/api/portfolio/summary').json()['capital']['cash']
    assert cash['total'] == -10000
    assert cash['available'] == 0
    assert cash['margin_shortfall'] == 10000
    recommendations = client.get('/api/rebalancing').json()['recommendations']
    assert any(row['code'] == 'eliminate_margin' and row['amount'] == 10000 for row in recommendations)


def test_allocation_cannot_be_deleted_without_reversing_transfers(account):
    client, _ = account
    client.post('/api/profit-ledger/realized', json={'source': 'leaps', 'occurred_on': '2026-08-25', 'amount': 2000})
    created = client.post('/api/profit-ledger/allocations', json={'occurred_on': '2026-08-26', 'amount': 1200, 'allocations': {'core': 700, 'cash': 500}}).json()
    entry = next(row for row in created['entries'] if row['entry_type'] == 'allocation')
    before = client.get('/api/portfolio/summary').json()['balances']
    response = client.post(f"/api/profit-ledger/entries/{entry['id']}/delete", json={'confirmation': 'DELETE'})
    assert response.status_code == 409
    assert entry['deletable'] is False
    assert client.get('/api/portfolio/summary').json()['balances'] == before
    assert client.get('/api/profit-ledger').json()['summary']['available'] == 800


@pytest.mark.parametrize('symbol,asset_type', [('QQQ', 'option'), ('QLD', 'equity')])
def test_calendar_risk_advances_even_when_quotes_are_old(account, symbol, asset_type):
    client, sessions = account
    today = date.today()
    with sessions() as session:
        session.add(PositionRecord(bucket='leaps', symbol=symbol, asset_type=asset_type, direction='long', option_type='call' if asset_type == 'option' else None, quantity=1, multiplier=100 if asset_type == 'option' else 1, entry_price=100, current_price=100, opened_on=today-timedelta(days=300), expiration=today+timedelta(days=60) if asset_type == 'option' else None, quote_as_of=datetime.combine(today-timedelta(days=60), datetime.min.time()), quote_quality='stale', last_error='synthetic offline'))
        session.commit()
    decision = client.get('/api/positions').json()[0]['exit_decision']
    assert decision['days_held'] == 300
    if asset_type == 'option':
        assert decision['dte'] == 60
        assert decision['code'] == 'force_exit'


def test_nested_wheel_service_does_not_commit_a_partial_import(account):
    from app.db_models import WheelRound
    client, sessions = account
    content = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,2026-08-26
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Close Price
Open Positions,Data,Summary,Equity and Index Options,USD,TQQQ 16OCT26 40 P,-1,100,2,1
Open Positions,Data,Summary,Stocks,USD,BRK B,1000,1,500,500
'''
    assert upload(client, content).status_code == 409
    with sessions() as session:
        assert list(session.scalars(select(WheelPutLot))) == []
        assert list(session.scalars(select(WheelRound))) == []
        assert list(session.scalars(select(BrokerImportRecord))) == []


def test_non_usd_account_nav_is_rejected_without_business_writes(account):
    client, _ = account
    content = statement(nav=780000) + 'Account Information,Header,Field Name,Field Value\nAccount Information,Data,Base Currency,HKD\n'
    assert upload(client, content).status_code == 409
    assert client.get('/api/positions').json() == []
    assert client.get('/api/portfolio/summary').json()['total_equity'] == 100000


def test_legacy_nav_cash_adjustment_is_migrated_once(tmp_path):
    from app.db_models import BucketBalance, LedgerEvent, BrokerAccountSnapshot
    from app.services.portfolio_store import PortfolioStore
    from app.services.rebalancing import RebalancingService
    engine = create_engine(f'sqlite+pysqlite:///{tmp_path / "legacy-nav.db"}')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        PortfolioStore(session).initialize(36, Decimal('100000'), date(2026, 8, 1))
        session.add(PositionRecord(bucket='core', symbol='BRK.B', asset_type='equity', direction='long', quantity=10, multiplier=1, entry_price=500, current_price=600, opened_on=date(2026, 8, 1)))
        session.get(BucketBalance, 'cash').amount += 1000
        session.add(LedgerEvent(event_type='broker_nav_reconciliation', bucket='cash', amount=1000, occurred_on=date(2026, 8, 25), details={'ending_value': 101000}))
        session.commit()
    for _ in range(2):
        initialize_database(engine)
        with Session(engine) as session:
            assert session.get(BucketBalance, 'cash').amount == 5000
            assert session.get(BrokerAccountSnapshot, 1).net_asset_value == 101000
            assert PortfolioStore(session).summary()['total_equity'] == 101000
            assert RebalancingService(session).evaluate(date(2026, 8, 26))['economic']['total'] == 101000
    engine.dispose()


def test_historical_deposit_already_in_reported_nav_does_not_increase_nav_again(account):
    client, _ = account
    upload(client, statement(nav=101000))
    content = 'Statement,Header,Field Name,Field Value\nStatement,Data,Period,2026-08-24\nDeposits & Withdrawals,Header,Currency,Settle Date,Description,Amount\nDeposits & Withdrawals,Data,USD,2026-08-20,Historical synthetic deposit,1000\n'
    assert upload(client, content).status_code == 200
    portfolio = client.get('/api/portfolio/summary').json()
    assert portfolio['total_equity'] == 101000
    assert portfolio['net_external_capital'] == 101000
    assert portfolio['balances']['cash'] == 6000
    assert portfolio['valuation']['valuation_adjustment'] == 0


def test_older_snapshot_cannot_resurrect_a_manually_closed_position(account):
    client, _ = account
    content = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,2026-08-25
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Close Price
Open Positions,Data,Summary,Equity and Index Options,USD,QQQ 18JUN27 400 C,1,100,100,100
'''
    assert upload(client, content).status_code == 200
    position = client.get('/api/positions').json()[0]
    assert client.post(f"/api/positions/{position['id']}/close", json={'date': '2026-08-26', 'price': 110}).status_code == 200
    response = upload(client, content)
    assert response.status_code == 200
    assert client.get('/api/positions').json() == []


def test_reset_clears_statement_dates_and_nav_observations(account):
    from app.db_models import BrokerAccountSnapshot, BrokerPositionSnapshot
    client, sessions = account
    upload(client, statement(nav=101000))
    assert client.post('/api/system/reset', json={'confirmation': 'RESET'}).status_code == 200
    with sessions() as session:
        assert list(session.scalars(select(BrokerAccountSnapshot))) == []
        assert list(session.scalars(select(BrokerPositionSnapshot))) == []


def test_full_report_can_complete_an_existing_same_date_nav_observation(account):
    client, _ = account
    summary = 'Statement,Header,Field Name,Field Value\nStatement,Data,Period,2026-08-25\nAccount Information,Header,Field Name,Field Value\nAccount Information,Data,Base Currency,USD\nChange in NAV,Header,Field Name,Field Value\nChange in NAV,Data,Ending Value,101000\n'
    assert upload(client, summary).status_code == 200
    assert upload(client, statement(price=600, nav=101000)).status_code == 200
    portfolio = client.get('/api/portfolio/summary').json()
    assert portfolio['total_equity'] == 101000
    assert portfolio['valuation']['valuation_adjustment'] == 0


def test_summary_requires_explicit_usd_base_currency(account):
    client, _ = account
    content = statement(nav=100000).replace('Account Information,Data,Base Currency,USD\n', '')
    assert upload(client, content).status_code == 409
    assert client.get('/api/positions').json() == []


@pytest.mark.parametrize('symbol,asset_type', [('QQQ', 'option'), ('QLD', 'equity')])
def test_old_legacy_quote_cannot_trigger_a_price_exit(account, symbol, asset_type):
    client, sessions = account
    today = date.today()
    with sessions() as session:
        session.add(PositionRecord(bucket='leaps', symbol=symbol, asset_type=asset_type, direction='long', option_type='call' if asset_type == 'option' else None, quantity=1, multiplier=100 if asset_type == 'option' else 1, entry_price=100, current_price=200, quote_bid=200, opened_on=today-timedelta(days=100), expiration=today+timedelta(days=300) if asset_type == 'option' else None, quote_as_of=datetime.combine(today-timedelta(days=60), datetime.min.time())))
        session.commit()
    decision = client.get('/api/positions').json()[0]['exit_decision']
    assert decision['days_held'] == 100
    assert decision['actionable'] is False


def test_duplicate_confirm_selections_do_not_duplicate_business_records(account):
    client, _ = account
    content = statement()
    preview = client.post('/api/imports/ibkr/preview', json={'filename': 'synthetic.csv', 'content': content}).json()
    fingerprint = preview['rows'][0]['fingerprint']
    response = client.post('/api/imports/ibkr/confirm', json={'filename': 'synthetic.csv', 'content': content, 'selected_fingerprints': [fingerprint, fingerprint], 'overrides': {}, 'confirmation': 'IMPORT'})
    assert response.status_code == 200, response.text
    assert response.json()['imported'] == 1
    assert len(client.get('/api/positions').json()) == 1


def test_backfilled_close_cannot_close_a_more_recent_position_snapshot(account):
    client, _ = account
    content = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,2026-08-26
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Close Price
Open Positions,Data,Summary,Equity and Index Options,USD,QQQ 18JUN27 400 C,1,100,100,100
'''
    assert upload(client, content).status_code == 200
    historical = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,2026-08-25
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,Code
Trades,Data,Order,Equity and Index Options,USD,QQQ 18JUN27 400 C,2026-08-25 10:00:00,-1,110,C
'''
    response = upload(client, historical)
    assert response.status_code == 200, response.text
    assert response.json()['needs_attention'] == 1
    assert len(client.get('/api/positions').json()) == 1


def test_legacy_matching_report_establishes_dates_without_using_new_quote_time(account):
    client, sessions = account
    with sessions() as session:
        session.add(PositionRecord(bucket='core', symbol='BRK.B', asset_type='equity', direction='long', quantity=10, multiplier=1, entry_price=500, current_price=550, opened_on=date(2026, 8, 1), quote_as_of=datetime(2026, 10, 2), quote_source='ibkr'))
        session.commit()
    rejected = upload(client, statement('2026-08-25', quantity=5))
    assert rejected.json()['needs_attention'] == 1
    matched = upload(client, statement('2026-10-01'))
    assert matched.json()['unchanged'] == 1
    changed = upload(client, statement('2026-10-02', quantity=20))
    assert changed.json()['imported'] == 1
    assert client.get('/api/positions').json()[0]['quantity'] == 20
