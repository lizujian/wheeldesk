import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

from ib_async import Stock, Option
import pytest

from app.market.base import MarketDataError, option_quote_usable
from app.market.ibkr import IbkrMarketDataProvider, broker_symbol
from app.market.ibkr_connection import IbkrConnection

NOW = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
EXPIRY = date(2026, 11, 6)


class Connection:
    def __init__(self):
        self.calls = []
        self.change = {}
        self.data_type = 2
        self.missing = False

    def call(self, method, **kwargs):
        self.calls.append((method, kwargs))
        if method == "details":
            c = kwargs["contract"]
            c.conId = 101 if c.secType == "STK" else 102
            c.localSymbol = "AVGO  261106C00390000" if c.secType == "OPT" else c.symbol
            for key, value in self.change.items():
                setattr(c, key, value)
            return [SimpleNamespace(contract=c, liquidSessions=lambda: [SimpleNamespace(start=NOW-timedelta(hours=1), end=NOW+timedelta(hours=1))])]
        if method == "snapshots":
            return {} if self.missing else {c.conId: {"bid": 3.3, "ask": 4.3, "last": float("nan"), "close": 4,
                    "market_data_type": self.data_type, "fetched_at": NOW, "market_as_of": None, "iv": None}
                    for c in kwargs["contracts"]}
        if method == "history":
            return [SimpleNamespace(date=NOW.date()-timedelta(days=days), open=100, high=101,
                       low=99, close=100, volume=1000) for days in range(350,-1,-1)]
        raise AssertionError(method)

    def error_for(self, con_id):
        return "IBKR 10089：API 行情未订阅"


def provider(connection=None):
    return IbkrMarketDataProvider(connection or Connection(), now=lambda: NOW)


def test_frozen_book_is_usable_without_last_or_iv_and_is_not_live():
    quote = provider().option_quote("AVGO", "call", EXPIRY, Decimal(390))
    assert quote.bid == Decimal("3.3") and quote.ask == Decimal("4.3")
    assert quote.source == "ibkr" and quote.quality == "closed"
    assert quote.market_as_of is None and quote.implied_volatility is None
    assert option_quote_usable(quote, NOW.date())


@pytest.mark.parametrize("change", [{"symbol": "NVDA"}, {"strike": 380}, {"right": "P"},
    {"lastTradeDateOrContractMonth": "20261113"}, {"multiplier": "10"}, {"tradingClass": "AVGO1"}, {"currency": "EUR"}])
def test_wrong_or_adjusted_contract_is_rejected(change):
    connection = Connection(); connection.change = change
    with pytest.raises(MarketDataError, match="未唯一匹配"):
        provider(connection).option_quote("AVGO", "call", EXPIRY, Decimal(390))


def test_history_excludes_today_sorts_and_keeps_300_bars():
    series = provider().daily_bars("QQQ")
    assert len(series.bars) == 300 and series.as_of == NOW.date()-timedelta(days=1)
    assert series.source == "ibkr"
    assert series.bars == sorted(series.bars, key=lambda b: b.date)


def test_missing_stock_quote_reports_failure_without_another_data_source():
    connection = Connection(); connection.missing = True
    p = provider(connection)
    with pytest.raises(MarketDataError, match="10089"):
        p.session_quote("AVGO")
    assert "10089" in p.warnings()[0]["error"]


def test_vix_qualifies_the_cboe_index_and_returns_completed_ibkr_history():
    connection = Connection()
    series = provider(connection).daily_bars("VIX", 5)
    contract = connection.calls[0][1]["contract"]
    assert (contract.symbol, contract.secType, contract.exchange, contract.currency) == ("VIX", "IND", "CBOE", "USD")
    assert series.source == "ibkr" and len(series.bars) == 5
    assert series.as_of == NOW.date()-timedelta(days=1)


def test_vix_context_history_includes_today_and_reloads_only_on_refresh():
    connection = Connection(); p = provider(connection)
    assert p.vix_history().as_of == NOW.date()
    p.vix_history()
    assert len([call for call in connection.calls if call[0] == 'history']) == 1
    p.begin_refresh()
    p.vix_history()
    assert len([call for call in connection.calls if call[0] == 'history']) == 2
    assert p.daily_bars('VIX', 5).as_of == NOW.date()-timedelta(days=1)


@pytest.mark.parametrize("change", [{"secType": "STK"}, {"symbol": "VIXY"}, {"exchange": "SMART"}])
def test_vix_does_not_match_an_equity_or_another_index(change):
    connection = Connection(); connection.change = change
    with pytest.raises(MarketDataError, match="CBOE 指数"):
        provider(connection).daily_bars("VIX", 5)


def test_prefetch_reuses_contract_and_quote_for_each_option():
    connection = Connection(); p = provider(connection)
    contract = ("AVGO", "call", EXPIRY, Decimal(390))
    p.prefetch_options([contract, contract]); p.option_quote(*contract)
    assert [method for method, _ in connection.calls] == ["details", "snapshots"]
    p.begin_refresh(); p.option_quote(*contract)
    assert [method for method, _ in connection.calls] == ["details", "snapshots", "snapshots"]


def test_missing_option_quote_keeps_failure_explicit():
    connection = Connection(); connection.missing = True
    with pytest.raises(MarketDataError, match="10089"):
        provider(connection).option_quote("AVGO", "call", EXPIRY, Decimal(390))


def test_stock_alias_and_readonly_connection_rejects_order_operations():
    assert broker_symbol("BRK.B") == broker_symbol("BRK-B") == "BRK B"
    with pytest.raises(ValueError):
        IbkrConnection("localhost", 4001, 0)
    connection = IbkrConnection("localhost", 4001)
    try:
        with pytest.raises(MarketDataError, match="只读"):
            connection.call("placeOrder")
    finally:
        connection.close()


def test_brief_quote_query_cancels_subscription_on_cancellation(monkeypatch):
    class Client:
        def __init__(self):
            self.cancelled = []
        def isConnected(self):
            return True
        def reqMarketDataType(self, value):
            pass
        def reqMktData(self, contract, *args):
            return SimpleNamespace(contract=contract)
        def cancelMktData(self, contract):
            self.cancelled.append(contract)
        def disconnect(self):
            pass
    client = Client()
    connection = IbkrConnection("unused", 4001)
    connection._ib = client
    async def cancel(delay):
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, "sleep", cancel)
    contract = Stock("QQQ", "SMART", "USD")
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(connection._query("snapshots", {"contracts": [contract]}))
        assert client.cancelled == [contract]
    finally:
        connection.close()


class IvConnection(Connection):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def call(self, method, **kwargs):
        if method == "iv_history":
            self.calls.append((method, kwargs))
            return [SimpleNamespace(date=day, close=value) for day, value in self.rows]
        return super().call(method, **kwargs)


def test_iv_uses_today_after_open_and_refreshes_on_every_manual_request():
    connection = IvConnection([(date(2026, 10, 13), .2), (date(2026, 10, 14), .25)])
    p = provider(connection)
    comparison = p.implied_volatility("QQQ")
    assert comparison.latest.as_of == NOW.date()
    assert comparison.latest.value == Decimal(".25")
    assert comparison.previous.value == Decimal(".2")
    assert comparison.change_fraction == Decimal(".25")
    p.implied_volatility("QQQ")
    assert [method for method, _ in connection.calls].count("iv_history") == 1
    p.begin_refresh()
    p.implied_volatility("QQQ")
    assert [method for method, _ in connection.calls].count("iv_history") == 2


@pytest.mark.parametrize("method, load", [
    ("iv_history", lambda p: p.implied_volatility("QQQ")),
    ("history", lambda p: p.vix_history()),
])
def test_failed_prefetch_is_reused_for_the_entire_refresh_and_retried_next_time(monkeypatch, method, load):
    class FailingConnection(Connection):
        def call(self, requested, **kwargs):
            if requested == method:
                self.calls.append((requested, kwargs))
                raise MarketDataError("history timed out")
            return super().call(requested, **kwargs)

    clock = [100.0]
    monkeypatch.setattr("app.market.ibkr.monotonic", lambda: clock[0])
    connection = FailingConnection()
    p = provider(connection)
    p.begin_refresh()
    with pytest.raises(MarketDataError, match="history timed out"):
        load(p)  # parallel prefetch
    clock[0] += 20  # other symbols finish before the watchlist consumes the result
    with pytest.raises(MarketDataError, match="history timed out"):
        load(p)
    assert [requested for requested, _ in connection.calls].count(method) == 1
    p.begin_refresh()
    with pytest.raises(MarketDataError, match="history timed out"):
        load(p)
    assert [requested for requested, _ in connection.calls].count(method) == 2


def test_iv_before_open_uses_latest_two_valid_distinct_dates_and_skips_future_values():
    connection = IvConnection([(date(2026, 10, 14), .3), (date(2026, 10, 15), .9),
        (date(2026, 10, 13), .21), (date(2026, 10, 9), float("nan")),
        (date(2026, 10, 12), .25), (date(2026, 10, 13), .2), (date(2026, 10, 10), 0)])
    p = IbkrMarketDataProvider(connection, now=lambda: NOW-timedelta(hours=4))
    comparison = p.implied_volatility("AVGO")
    assert comparison.latest.as_of == date(2026, 10, 13)
    assert comparison.previous.as_of == date(2026, 10, 12)
    assert comparison.change_fraction == Decimal("-.2")
    assert comparison.source == "ibkr"


def test_iv_missing_today_uses_previous_available_sessions_across_a_weekend():
    comparison = provider(IvConnection([(date(2026, 10, 9), .2), (date(2026, 10, 12), .25)])).implied_volatility("SOXX")
    assert comparison.latest.as_of == date(2026, 10, 12)
    assert comparison.previous.as_of == date(2026, 10, 9)
    assert comparison.change_fraction == Decimal(".25")


def test_iv_with_only_one_day_keeps_comparison_unavailable():
    comparison = provider(IvConnection([(date(2026, 10, 13), .2)])).implied_volatility("DRAM")
    assert comparison.previous is None and comparison.change_fraction is None
    with pytest.raises(MarketDataError, match="历史 IV"):
        provider(IvConnection([(date(2026, 10, 13), -1)])).implied_volatility("DRAM")


def test_partial_watchlist_history_does_not_weaken_strategy_history_requirement():
    class ShortHistory(Connection):
        def call(self, method, **kwargs):
            rows = super().call(method, **kwargs)
            return rows[-135:] if method == "history" else rows
    connection = ShortHistory()
    p = provider(connection)
    assert len(p.watchlist_bars("DRAM").bars) == 134
    with pytest.raises(MarketDataError, match="不足 300"):
        p.daily_bars("DRAM")
    assert [method for method, _ in connection.calls].count("history") == 1


def test_ibkr_iv_history_uses_the_underlying_volatility_data_type():
    class Client:
        def isConnected(self): return True
        async def reqHistoricalDataAsync(self, contract, **kwargs):
            self.parameters = kwargs
            return []
        def disconnect(self): pass
    client = Client()
    connection = IbkrConnection("unused", 4001)
    connection._ib = client
    try:
        asyncio.run(connection._query("iv_history", {"contract": Stock("QQQ", "SMART", "USD")}))
        assert client.parameters["whatToShow"] == "OPTION_IMPLIED_VOLATILITY"
        assert client.parameters["barSizeSetting"] == "1 day"
        assert client.parameters["timeout"] == 15
    finally:
        connection.close()
