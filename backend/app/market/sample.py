import math
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from app.domain.indicators import DailyBar
from app.market.base import MarketCapitalization, MarketDataError, MarketSeries, SessionQuote

BASE_PRICES = {"QQQ": 520.0, "TQQQ": 85.0, "BRK.B": 490.0, "VIX": 18.0}


class SampleMarketDataProvider:
    def __init__(self, as_of: date | None = None) -> None:
        self.as_of = as_of or date.today()

    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries:
        normalized = symbol.upper()
        base = BASE_PRICES.get(normalized, 100.0)
        dates = _business_dates(self.as_of, max(limit, 300))
        bars: list[DailyBar] = []
        for index, day in enumerate(dates):
            trend = 0.00065 * index
            cycle = math.sin(index / 11) * 0.035 + math.sin(index / 37) * 0.06
            close = base * (0.84 + trend + cycle)
            open_price = close * (1.004 if index % 5 in (0, 1) else 0.997)
            spread = close * 0.012
            bars.append(
                DailyBar(
                    date=day,
                    open=Decimal(str(round(open_price, 4))),
                    high=Decimal(str(round(max(open_price, close) + spread, 4))),
                    low=Decimal(str(round(min(open_price, close) - spread, 4))),
                    close=Decimal(str(round(close, 4))),
                    volume=1_000_000 + index * 1_337,
                )
            )
        return MarketSeries(symbol=normalized, bars=bars[-limit:], source="sample")

    def session_quote(self, symbol: str) -> SessionQuote:
        series = self.daily_bars(symbol, 2)
        return SessionQuote(
            symbol=series.symbol,
            price=series.bars[-1].close,
            previous_close=series.bars[-2].close,
            quoted_at=datetime.combine(self.as_of, time(21), tzinfo=timezone.utc),
            market_date=self.as_of,
            session="sample",
            source="sample",
        )

    def market_cap(self, symbol: str) -> MarketCapitalization:
        return MarketCapitalization(
            symbol=symbol.upper(),
            value=Decimal("0"),
            currency="USD",
            as_of=self.as_of,
            source="sample",
        )

    def earnings_date(self, symbol: str):
        raise MarketDataError(f"{symbol.upper()} 模拟数据不提供财报日期")


def _business_dates(end: date, count: int) -> list[date]:
    result: list[date] = []
    cursor = end
    while len(result) < count:
        if cursor.weekday() < 5:
            result.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(result))
