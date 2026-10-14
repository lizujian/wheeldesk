"""Market observations for the LEAPS list, independent of entry decisions."""
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor

from app.domain.indicators import simple_moving_average, wilder_rsi
from app.domain.trillion_club import TRILLION_CLUB_CANDIDATES
from app.market.base import MarketDataError, completed_daily_bars

PINNED_LEAPS_SYMBOLS = {"QQQ": "Invesco QQQ", "DRAM": "Roundhill Memory ETF", "SOXX": "iShares Semiconductor ETF"}


def load_leaps_watchlist(provider, club_symbols, known_series, *, refresh_iv=True):
    symbols = list(dict.fromkeys([*PINNED_LEAPS_SYMBOLS, *club_symbols]))
    with ThreadPoolExecutor(max_workers=6) as executor:
        return list(executor.map(lambda symbol: _load_row(provider, symbol, known_series, refresh_iv=refresh_iv), symbols))


def _load_row(provider, symbol, known_series, *, refresh_iv):
    row = {"symbol": symbol, "name": PINNED_LEAPS_SYMBOLS.get(symbol, TRILLION_CLUB_CANDIDATES.get(symbol, symbol)),
           "price": None, "change_fraction": None, "ma200": None, "rsi14": None,
           "source": None, "error": None, "iv": None, "iv_error": None, "completed_sessions": None}
    try:
        quote = provider.session_quote(symbol)
        row.update(price=quote.price, change_fraction=quote.change_fraction, source=quote.source,
                   price_kind="snapshot", session=quote.session, market_session=quote.market_session,
                   quality=quote.quality, market_as_of=quote.market_as_of, fetched_at=quote.fetched_at,
                   exchange=quote.exchange, session_error=quote.session_error)
    except (AttributeError, MarketDataError, OSError) as error:
        quote = None
        row["error"] = str(error)
    try:
        loader = getattr(provider, "watchlist_bars", provider.daily_bars)
        series = known_series.get(symbol) or loader(symbol, 300)
        bars = completed_daily_bars(series, quote) if quote else series.bars
        closes = [bar.close for bar in bars]
        row.update(ma200=simple_moving_average(closes, 200) if len(closes) >= 200 else None,
                   rsi14=wilder_rsi(closes) if len(closes) >= 15 else None, completed_sessions=len(closes))
        if quote is None:
            row.update(price=closes[-1], change_fraction=closes[-1] / closes[-2] - 1 if len(closes) > 1 else None,
                       source=series.source, price_kind="close", session="closed", market_as_of=bars[-1].date)
    except (AttributeError, MarketDataError, OSError, ValueError, IndexError) as error:
        row["error"] = str(error)
    if refresh_iv:
        try:
            row["iv"] = asdict(provider.implied_volatility(symbol))
        except (AttributeError, MarketDataError, OSError) as error:
            row["iv_error"] = str(error) if not isinstance(error, AttributeError) else "当前数据源未提供标的历史 IV"
    else:
        row["iv_error"] = "IV 仅在全量刷新时更新"
    return row
