from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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
    quality: str = "legacy"
    fetched_at: datetime | None = None
    market_as_of: datetime | None = None
    market_session: str | None = None
    exchange: str | None = None
    session_error: str | None = None

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
class ImpliedVolatilityPoint:
    as_of: date
    value: Decimal


@dataclass(frozen=True)
class ImpliedVolatilityComparison:
    symbol: str
    latest: ImpliedVolatilityPoint
    previous: ImpliedVolatilityPoint | None
    change_fraction: Decimal | None
    source: str
    fetched_at: datetime


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
    implied_volatility: Decimal | None
    quoted_at: datetime
    source: str
    quality: str = "legacy"
    fetched_at: datetime | None = None
    market_as_of: datetime | None = None


def session_quote_live(quote: SessionQuote | None) -> bool:
    return quote is not None and quote.source != "sample" and quote.quality in {"legacy", "realtime"}


def option_quote_usable(quote: OptionQuote, as_of: date) -> bool:
    if quote.bid <= 0 or quote.ask <= 0 or quote.ask < quote.bid:
        return False
    if quote.quality in {"stale", "unavailable"}:
        return False
    # IBKR book quotes have a retrieval time independent of the last trade.
    if quote.source == "ibkr":
        return quote.quality in {"realtime", "closed", "delayed", "unknown"}
    return abs((as_of - quote.quoted_at.date()).days) <= 5


def quote_metadata(quote) -> dict:
    return {
        "quote_vendor": quote.source,
        "quote_quality": quote.quality,
        "quote_fetched_at": quote.fetched_at,
        "quote_market_as_of": quote.market_as_of,
    }


def stored_quote_metadata(record) -> dict:
    def utc(value):
        return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value
    fetched = utc(record.quote_fetched_at)
    quality = record.quote_quality
    if quality == "realtime" and fetched and (datetime.now(timezone.utc) - fetched).total_seconds() > 120:
        quality = "stale"
    return {"quote_vendor": record.quote_vendor, "quote_quality": quality,
            "quote_fetched_at": fetched, "quote_market_as_of": utc(record.quote_market_as_of)}


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
