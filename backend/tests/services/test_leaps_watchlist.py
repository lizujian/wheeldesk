from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.domain.indicators import DailyBar
from app.market.base import (ImpliedVolatilityComparison, ImpliedVolatilityPoint,
                             MarketDataError, MarketSeries, SessionQuote)
from app.services.leaps_watchlist import load_leaps_watchlist

NOW = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)


class Provider:
    def session_quote(self, symbol):
        return SessionQuote(symbol, Decimal(55), Decimal(50), NOW, NOW.date(), "pre", "ibkr", "delayed")

    def daily_bars(self, symbol, limit):
        count = 134 if symbol == "DRAM" else 300
        return MarketSeries(symbol, [DailyBar(NOW.date()-timedelta(days=count-i),
            Decimal(50), Decimal(51), Decimal(49), Decimal(50), 1000) for i in range(count)], "ibkr")

    def implied_volatility(self, symbol):
        if symbol == "SOXX":
            raise MarketDataError("SOXX IV unavailable")
        return ImpliedVolatilityComparison(symbol,
            ImpliedVolatilityPoint(date(2026, 10, 13), Decimal(".25")),
            ImpliedVolatilityPoint(date(2026, 10, 12), Decimal(".2")), Decimal(".25"), "ibkr", NOW)


def test_watchlist_pins_etfs_and_keeps_prices_when_iv_or_long_history_is_missing():
    rows = load_leaps_watchlist(Provider(), ["AVGO", "DRAM"], {})
    assert [row["symbol"] for row in rows] == ["QQQ", "DRAM", "SOXX", "AVGO"]
    assert rows[0]["iv"]["latest"]["value"] == Decimal(".25")
    assert rows[0]["iv"]["previous"]["as_of"] == date(2026, 10, 12)
    assert rows[1]["price"] == 55 and rows[1]["rsi14"] == 50
    assert rows[1]["ma200"] is None and rows[1]["completed_sessions"] == 134
    assert rows[2]["price"] == 55 and rows[2]["ma200"] == 50
    assert rows[2]["iv"] is None and rows[2]["iv_error"] == "SOXX IV unavailable"


def test_watchlist_keeps_current_price_and_iv_when_history_is_unavailable():
    class MissingHistory(Provider):
        def daily_bars(self, symbol, limit):
            raise MarketDataError("history unavailable")
    row = load_leaps_watchlist(MissingHistory(), [], {})[0]
    assert row["price"] == 55 and row["iv"] is not None
    assert row["ma200"] is None and row["error"] == "history unavailable"
