from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.domain.indicators import DailyBar
from app.market.base import MarketDataError, MarketSeries, SessionQuote
from app.services.vix_context import load_vix_context

DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 14, tzinfo=timezone.utc)


def bar(day, close, high=None):
    close = Decimal(str(close))
    return DailyBar(day, close, Decimal(str(high)) if high else close, close, close, 0)


class Provider:
    price = Decimal(20)

    def session_quote(self, symbol):
        return SessionQuote(symbol, self.price, Decimal(19), NOW, DAY, 'regular', 'ibkr', 'delayed', NOW, NOW)

    def vix_history(self):
        start = DAY - timedelta(weeks=52)
        rows = [bar(start + timedelta(days=i), 10 if i % 2 == 0 else 20, 25) for i in range(364)]
        return MarketSeries('VIX', [bar(start-timedelta(days=1), 100, 999), *rows, bar(DAY, 100, 40)], 'ibkr')


@pytest.mark.parametrize('price,expected', [(5, 0), (10, Decimal('.5')), (20, 1), (50, 1)])
def test_percentile_uses_completed_closes_in_52_weeks_with_ties(price, expected):
    provider = Provider(); provider.price = Decimal(price)
    result = load_vix_context(provider, as_of=DAY)
    assert result['percentile_fraction'] == expected
    assert result['sample_size'] == 364  # today's unfinished close and older bars excluded
    assert result['high_52w'] == max(Decimal(40), provider.price)
    assert result['high_52w_as_of'] == DAY
    assert result['price_kind'] == 'snapshot' and result['quality'] == 'delayed'
    assert result['history_error'] is None


def test_missing_snapshot_uses_completed_close_not_unfinished_today():
    class MissingQuote(Provider):
        def session_quote(self, symbol):
            raise MarketDataError('snapshot unavailable')
    result = load_vix_context(MissingQuote(), as_of=DAY)
    assert result['price'] == 20 and result['price_kind'] == 'close'
    assert result['close_as_of'] == DAY-timedelta(days=1)
    assert result['percentile_fraction'] == 1
    assert result['error'] == 'snapshot unavailable'


def test_history_failure_does_not_hide_current_vix_or_invent_statistics():
    class MissingHistory(Provider):
        def vix_history(self):
            raise MarketDataError('history unavailable')
    result = load_vix_context(MissingHistory(), as_of=DAY)
    assert result['price'] == 20
    assert result['high_52w'] is None and result['percentile_fraction'] is None
    assert result['history_error'] == 'history unavailable'


def test_partial_history_is_not_presented_as_a_52_week_statistic():
    class PartialHistory(Provider):
        def vix_history(self):
            return MarketSeries('VIX', [bar(DAY-timedelta(days=1), 20)], 'ibkr')
    result = load_vix_context(PartialHistory(), as_of=DAY)
    assert result['price'] == 20 and result['sample_size'] == 1
    assert result['high_52w'] is None and result['percentile_fraction'] is None
    assert '不完整' in result['history_error']
