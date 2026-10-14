"""VIX observations for display, independent of strategy decision inputs."""
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.market.base import MarketDataError


def load_vix_context(provider, *, as_of=None):
    as_of = as_of or datetime.now(ZoneInfo("America/New_York")).date()
    start = as_of - timedelta(weeks=52)
    result = dict(price=None, price_kind=None, source=None, quality=None, market_as_of=None,
                  fetched_at=None, close_as_of=None, high_52w=None, high_52w_as_of=None,
                  percentile_fraction=None, sample_size=0, window_start=start, window_end=as_of,
                  error=None, history_error=None)
    try:
        quote = provider.session_quote("VIX")
        result.update(price=quote.price, price_kind="snapshot", source=quote.source, quality=quote.quality,
                      market_as_of=quote.market_as_of, fetched_at=quote.fetched_at)
    except (AttributeError, MarketDataError, OSError) as error:
        result["error"] = str(error)
    try:
        loader = getattr(provider, "vix_history", None)
        series = loader() if loader else provider.daily_bars("VIX", 300)
        bars = {bar.date: bar for bar in series.bars if bar.date <= as_of and bar.close > 0 and bar.high > 0}
        completed = [bars[day] for day in sorted(bars) if day < as_of]
        if not completed:
            raise MarketDataError("VIX 缺少有效完成日线")
        latest = completed[-1]
        result["close_as_of"] = latest.date
        if result["price"] is None:
            result.update(price=latest.close, price_kind="close", source=series.source, quality="close")
        window = [bar for bar in bars.values() if bar.date >= start]
        samples = [bar.close for bar in completed if bar.date >= start]
        result["sample_size"] = len(samples)
        # Require a full year of coverage; a new or partial series is not a 52-week statistic.
        if min(bars) > start + timedelta(days=7) or (as_of - latest.date).days > 7 or len(samples) < 200:
            raise MarketDataError("VIX 近 52 周历史不完整或已过期")
        high_bar = max(window, key=lambda bar: (bar.high, bar.date))
        high, high_date = high_bar.high, high_bar.date
        if result["price_kind"] == "snapshot" and result["price"] > high:
            high, high_date = result["price"], as_of
        result.update(high_52w=high, high_52w_as_of=high_date,
                      percentile_fraction=Decimal(sum(value <= result["price"] for value in samples)) / len(samples))
    except (AttributeError, MarketDataError, OSError, ValueError) as error:
        result["history_error"] = str(error)
    return result
