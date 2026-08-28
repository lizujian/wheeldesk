from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.domain.indicators import DailyBar


class MarketDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketSeries:
    symbol: str
    bars: list[DailyBar]
    source: str

    @property
    def as_of(self) -> date:
        if not self.bars:
            raise MarketDataError("行情数据为空")
        return self.bars[-1].date


@dataclass(frozen=True)
class SessionQuote:
    symbol: str
    price: Decimal
    previous_close: Decimal
    quoted_at: datetime
    market_date: date
    session: str
    source: str

    @property
    def change_fraction(self) -> Decimal | None:
        if self.previous_close <= 0:
            return None
        return (self.price - self.previous_close) / self.previous_close


@dataclass(frozen=True)
class MarketCapitalization:
    symbol: str
    value: Decimal
    currency: str
    as_of: date
    source: str


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    event_date: date
    source: str


@dataclass(frozen=True)
class OptionQuote:
    contract_symbol: str
    symbol: str
    option_type: str
    expiration: date
    strike: Decimal
    bid: Decimal
    ask: Decimal
    last: Decimal
    implied_volatility: Decimal
    quoted_at: datetime
    source: str


class MarketDataProvider(Protocol):
    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries: ...

    def session_quote(self, symbol: str) -> SessionQuote: ...

    def market_cap(self, symbol: str) -> MarketCapitalization: ...

    def earnings_date(self, symbol: str) -> EarningsEvent: ...


class OptionDataProvider(Protocol):
    def option_quote(
        self,
        symbol: str,
        option_type: str,
        expiration: date,
        strike: Decimal,
    ) -> OptionQuote: ...


class FallbackMarketDataProvider:
    def __init__(self, primary: MarketDataProvider, fallback: MarketDataProvider) -> None:
        self.primary = primary
        self.fallback = fallback

    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries:
        try:
            return self.primary.daily_bars(symbol, limit)
        except (MarketDataError, OSError):
            return self.fallback.daily_bars(symbol, limit)

    def session_quote(self, symbol: str) -> SessionQuote:
        try:
            return self.primary.session_quote(symbol)
        except (MarketDataError, OSError):
            return self.fallback.session_quote(symbol)

    def market_cap(self, symbol: str) -> MarketCapitalization:
        try:
            return self.primary.market_cap(symbol)
        except (AttributeError, MarketDataError, OSError):
            return self.fallback.market_cap(symbol)

    def earnings_date(self, symbol: str) -> EarningsEvent:
        try:
            return self.primary.earnings_date(symbol)
        except (AttributeError, MarketDataError, OSError):
            return self.fallback.earnings_date(symbol)


def completed_daily_bars(
    series: MarketSeries,
    quote: SessionQuote,
) -> list[DailyBar]:
    bars = list(series.bars)
    if (
        series.source != "sample"
        and quote.source != "sample"
        and quote.session in {"pre", "regular"}
        and bars
        and bars[-1].date == quote.market_date
    ):
        return bars[:-1]
    return bars


def is_stale(as_of: date, today: date, max_age: timedelta = timedelta(days=5)) -> bool:
    return today - as_of > max_age
