from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.domain.indicators import DailyBar
from app.market.base import (
    FallbackMarketDataProvider,
    MarketDataError,
    MarketSeries,
    SessionQuote,
    completed_daily_bars,
    is_stale,
)
from app.market.sample import SampleMarketDataProvider


class BrokenProvider:
    def daily_bars(self, symbol: str, limit: int = 300):
        raise MarketDataError("offline")

    def session_quote(self, symbol: str):
        raise MarketDataError("offline")


def test_sample_provider_returns_deterministic_completed_history() -> None:
    series = SampleMarketDataProvider(as_of=date(2026, 7, 9)).daily_bars("QQQ", 260)

    assert series.symbol == "QQQ"
    assert series.source == "sample"
    assert len(series.bars) == 260
    assert series.bars[-1].date == date(2026, 7, 9)


def test_fallback_provider_marks_sample_source() -> None:
    provider = FallbackMarketDataProvider(
        primary=BrokenProvider(),
        fallback=SampleMarketDataProvider(as_of=date(2026, 7, 9)),
    )

    assert provider.daily_bars("TQQQ").source == "sample"
    quote = provider.session_quote("QQQ")
    assert quote.source == "sample"
    assert quote.session == "sample"
    assert quote.market_date == date(2026, 7, 9)


def test_staleness_uses_last_completed_bar_date() -> None:
    assert is_stale(date(2026, 7, 1), date(2026, 7, 10), max_age=timedelta(days=5)) is True
    assert is_stale(date(2026, 7, 9), date(2026, 7, 10), max_age=timedelta(days=5)) is False


def test_current_daily_candle_is_excluded_until_regular_session_completes() -> None:
    bars = [
        DailyBar(day, Decimal("100"), Decimal("101"), Decimal("99"), close, 1000)
        for day, close in (
            (date(2026, 8, 7), Decimal("100")),
            (date(2026, 8, 10), Decimal("98")),
        )
    ]
    series = MarketSeries("QQQ", bars, "yahoo")

    def quote(session: str) -> SessionQuote:
        return SessionQuote(
            "QQQ",
            Decimal("98"),
            Decimal("100"),
            datetime(2026, 8, 10, 14, tzinfo=timezone.utc),
            date(2026, 8, 10),
            session,
            "yahoo",
        )

    assert [bar.date for bar in completed_daily_bars(series, quote("pre"))] == [date(2026, 8, 7)]
    assert [bar.date for bar in completed_daily_bars(series, quote("regular"))] == [date(2026, 8, 7)]
    assert [bar.date for bar in completed_daily_bars(series, quote("post"))] == [
        date(2026, 8, 7),
        date(2026, 8, 10),
    ]
