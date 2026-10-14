"""Overlap independent broker reads before applying their results to the ledger."""
from concurrent.futures import ThreadPoolExecutor

from app.market.base import MarketDataError


def prefetch_market_data(provider, symbols, contracts, history_symbols, iv_symbols):
    calls = [(provider.prefetch_quotes, (symbols, contracts))]
    # VIX history can be slow; start it alongside the batched quote request.
    if hasattr(provider, "vix_history"):
        calls.insert(0, (provider.vix_history, ()))
    history_loader = getattr(provider, "watchlist_bars", provider.daily_bars)
    calls.extend((history_loader, (symbol, 300)) for symbol in dict.fromkeys(history_symbols))
    if hasattr(provider, "implied_volatility"):
        calls.extend((provider.implied_volatility, (symbol,)) for symbol in dict.fromkeys(iv_symbols))

    def fetch(call):
        method, args = call
        try:
            method(*args)
        except (MarketDataError, OSError):
            # Consumers report individual failures and preserve usable data.
            pass

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(fetch, calls))
