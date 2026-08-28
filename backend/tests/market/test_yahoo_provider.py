import json
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from app.market.yahoo import YahooMarketDataProvider


def test_yahoo_provider_normalizes_symbols_and_parses_complete_bars() -> None:
    requested_path = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_path
        requested_path = request.url.path
        payload = {
            "chart": {
                "result": [{
                    "timestamp": [1783555200, 1783641600],
                    "indicators": {"quote": [{
                        "open": [500.0, 502.0],
                        "high": [504.0, 505.0],
                        "low": [498.0, 500.0],
                        "close": [503.0, 504.0],
                        "volume": [1000, 1100],
                    }]},
                }],
                "error": None,
            }
        }
        return httpx.Response(200, content=json.dumps(payload))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = YahooMarketDataProvider(client=client)

    series = provider.daily_bars("BRK.B", limit=2)

    assert requested_path.endswith("/BRK-B")
    assert series.symbol == "BRK.B"
    assert series.source == "yahoo"
    assert series.bars[-1].date == date(2026, 7, 10)
    assert str(series.bars[-1].close) == "504.0"


def test_yahoo_provider_parses_premarket_session_quote() -> None:
    requested_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_params
        requested_params = dict(request.url.params)
        payload = {
            "chart": {
                "result": [{
                    "meta": {
                        "symbol": "QQQ",
                        "chartPreviousClose": 500.0,
                        "exchangeTimezoneName": "America/New_York",
                        "currentTradingPeriod": {
                            "pre": {"start": 1786352400, "end": 1786377600},
                            "regular": {"start": 1786377600, "end": 1786401000},
                            "post": {"start": 1786401000, "end": 1786415400},
                        },
                    },
                    "timestamp": [1786366800],
                    "indicators": {"quote": [{"close": [494.5]}]},
                }],
                "error": None,
            }
        }
        return httpx.Response(200, content=json.dumps(payload))

    provider = YahooMarketDataProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    quote = provider.session_quote("QQQ")

    assert requested_params["interval"] == "1m"
    assert requested_params["includePrePost"] == "true"
    assert quote.symbol == "QQQ"
    assert quote.price == Decimal("494.5")
    assert quote.previous_close == Decimal("500.0")
    assert quote.change_fraction == Decimal("-0.011")
    assert quote.session == "pre"
    assert quote.market_date == date(2026, 8, 10)
    assert quote.source == "yahoo"


def test_yahoo_provider_reads_latest_public_quarterly_market_cap() -> None:
    requested_type = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_type
        requested_type = request.url.params["type"]
        payload = {
            "timeseries": {
                "result": [{
                    "quarterlyMarketCap": [
                        {
                            "asOfDate": "2026-03-31",
                            "currencyCode": "USD",
                            "reportedValue": {"raw": 3_700_000_000_000},
                        },
                        {
                            "asOfDate": "2026-06-30",
                            "currencyCode": "USD",
                            "reportedValue": {"raw": 4_200_000_000_000},
                        },
                    ]
                }],
                "error": None,
            }
        }
        return httpx.Response(200, content=json.dumps(payload))

    provider = YahooMarketDataProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = provider.market_cap("AAPL")

    assert requested_type == "quarterlyMarketCap"
    assert result.value == Decimal("4200000000000")
    assert result.currency == "USD"
    assert result.as_of == date(2026, 6, 30)
    assert result.source == "yahoo"


def test_yahoo_provider_reads_next_public_earnings_date() -> None:
    expected = datetime(2026, 10, 29, tzinfo=timezone.utc)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["modules"] == "calendarEvents"
        payload = {
            "quoteSummary": {
                "result": [{
                    "calendarEvents": {
                        "earnings": {
                            "earningsDate": [{"raw": int(expected.timestamp())}]
                        }
                    }
                }],
                "error": None,
            }
        }
        return httpx.Response(200, content=json.dumps(payload))

    provider = YahooMarketDataProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    event = provider.earnings_date("AAPL")

    assert event.symbol == "AAPL"
    assert event.event_date == date(2026, 10, 29)
    assert event.source == "yahoo"
