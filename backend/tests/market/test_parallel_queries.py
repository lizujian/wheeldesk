import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.market.ibkr import IbkrMarketDataProvider
from app.market.ibkr_connection import IbkrConnection
from app.services.market_prefetch import prefetch_market_data


def test_independent_readonly_connection_queries_can_be_in_flight_together():
    connection = IbkrConnection('unused', 4001)
    active = 0
    async def query(method, kwargs):
        nonlocal active
        active += 1
        try:
            for _ in range(50):
                if active == 2: break
                await asyncio.sleep(.01)
            assert active == 2, 'independent history requests were serialized'
            await asyncio.sleep(.02)
            return kwargs['symbol']
        finally:
            active -= 1
    connection._query = query
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda symbol: connection.call('history', symbol=symbol), ['QQQ', 'SOXX']))
        assert values == ['QQQ', 'SOXX']
    finally:
        connection.close()


def test_provider_cache_allows_independent_fetches_but_coalesces_identical_requests():
    provider = IbkrMarketDataProvider(None)
    barrier = Barrier(2)
    def fetch(symbol):
        barrier.wait(timeout=1)
        return symbol
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(lambda symbol: provider._cached(('test', symbol), 30, lambda: fetch(symbol)), ['QQQ', 'SOXX']))
    assert values == ['QQQ', 'SOXX']
    count = 0
    def once():
        nonlocal count
        count += 1
        return 'shared'
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: provider._cached(('test', 'same'), 30, once), range(4))) == ['shared'] * 4
    assert count == 1


def test_connection_limits_independent_reads_to_six_and_serializes_market_data_type_changes():
    connection = IbkrConnection('unused', 4001)
    active, maximum = 0, 0
    class Client:
        async def reqContractDetailsAsync(self, contract):
            nonlocal active, maximum
            active += 1; maximum = max(active, maximum)
            await asyncio.sleep(.01)
            active -= 1
            return []
    async def connect(): return Client()
    connection._connect = connect
    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda _: connection.call('details', contract=None), range(12)))
        assert maximum == 6
        active, maximum = 0, 0
        async def snapshots(ib, kwargs):
            nonlocal active, maximum
            active += 1; maximum = max(active, maximum)
            await asyncio.sleep(.01)
            active -= 1
            return {}
        connection._snapshots = snapshots
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: connection.call('snapshots', contracts=[]), range(2)))
        assert maximum == 1
    finally:
        connection.close()


def test_refresh_overlaps_quotes_iv_and_vix_history_without_duplicating_symbols():
    barrier = Barrier(3)
    iv_symbols = []
    class Provider:
        def prefetch_quotes(self, symbols, contracts):
            assert symbols == ["QQQ"] and contracts == []
            barrier.wait(timeout=1)
        def vix_history(self):
            barrier.wait(timeout=1)
        def daily_bars(self, symbol, limit):
            assert symbol == "QQQ" and limit == 300
        def implied_volatility(self, symbol):
            iv_symbols.append(symbol)
            barrier.wait(timeout=1)
    prefetch_market_data(Provider(), ["QQQ"], [], ["QQQ", "QQQ"], ["QQQ", "QQQ"])
    assert iv_symbols == ["QQQ"]
