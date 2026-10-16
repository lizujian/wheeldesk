from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.market.ibkr import IbkrMarketDataProvider

NY = ZoneInfo('America/New_York')


class Connection:
    missing_night = False
    missing_time = False

    def __init__(self, now):
        self.now, self.calls = now, []

    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        if method == 'details':
            c = kwargs['contract']; c.conId = 101
            days = [self.now.replace(hour=0, minute=0) + timedelta(days=i) for i in [-1, 0, 1]]
            def sessions(start, end, overnight=False):
                return [SimpleNamespace(start=day.replace(hour=start), end=(day+timedelta(days=int(overnight))).replace(hour=end)) for day in days if day.weekday() < 5]
            return [SimpleNamespace(contract=c, validExchanges='SMART,OVERNIGHT',
                liquidSessions=lambda: sessions(9, 16),
                tradingSessions=lambda: sessions(20, 4, True) if c.exchange == 'OVERNIGHT' else sessions(4, 20))]
        if method == 'snapshots':
            rows = {}
            for c in kwargs['contracts']:
                if c.exchange == 'OVERNIGHT' and self.missing_night: continue
                stamp = self.now if c.exchange == 'OVERNIGHT' or not self.missing_night else self.now.replace(hour=15, minute=59)
                rows[c.conId] = dict(last=105 if c.exchange == 'OVERNIGHT' else 99, close=float('nan') if c.exchange == 'OVERNIGHT' else 100,
                    market_as_of=None if self.missing_time else stamp, fetched_at=self.now, market_data_type=3)
            return rows
        if method == 'history':
            return [SimpleNamespace(date=self.now.date()-timedelta(days=i), open=100, high=120, low=90,
                close=110 if i == 0 else 100, volume=10) for i in [2, 1, 0]]
        raise AssertionError(method)

    def error_for(self, con_id, *, sec_type=""): return 'night quote unavailable'


@pytest.mark.parametrize('hour,session,previous', [(8,'pre',100),(12,'regular',100),(18,'post',110),(22,'overnight',110),(2,'overnight',100)])
def test_price_uses_actual_session_and_extended_changes_reference_completed_regular_close(hour, session, previous):
    now = datetime(2026,10,14,hour,0,tzinfo=NY)
    c = Connection(now); p = IbkrMarketDataProvider(c,now=lambda:now)
    p.prefetch_snapshots(['QQQ'])
    quote = p.session_quote('QQQ')
    assert quote.session == quote.market_session == session
    assert quote.previous_close == previous
    assert quote.price == (105 if session == 'overnight' else 99)
    assert quote.exchange == ('OVERNIGHT' if session == 'overnight' else 'SMART')
    assert quote.market_as_of == now and quote.quality == 'delayed'
    if session == 'overnight':
        # SMART and OVERNIGHT use the same conId and must not share their prices.
        assert len([call for call in c.calls if call[0] == 'snapshots']) == 2


def test_missing_overnight_data_keeps_recent_regular_price_with_explicit_unavailability():
    now = datetime(2026,10,14,22,0,tzinfo=NY)
    c = Connection(now); c.missing_night = True
    p = IbkrMarketDataProvider(c,now=lambda:now); p.prefetch_snapshots(['QQQ'])
    quote = p.session_quote('QQQ')
    assert quote.price == 99 and quote.exchange == 'SMART'
    assert quote.market_session == 'overnight' and quote.session == 'regular'
    assert '夜盘' in quote.session_error


def test_unknown_trade_time_does_not_claim_the_last_trade_happened_in_premarket():
    now = datetime(2026,10,14,8,0,tzinfo=NY)
    c = Connection(now); c.missing_time = True
    quote = IbkrMarketDataProvider(c,now=lambda:now).session_quote('QQQ')
    assert quote.session == 'unknown' and quote.market_session == 'pre'
    assert quote.market_as_of is None


def test_overnight_venue_listing_does_not_mean_the_market_is_open_on_saturday():
    now = datetime(2026,10,17,22,0,tzinfo=NY)
    c = Connection(now)
    quote = IbkrMarketDataProvider(c,now=lambda:now).session_quote('QQQ')
    assert quote.market_session == 'closed' and quote.exchange == 'SMART'
