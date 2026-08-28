import json
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

from app.market.yahoo import YahooMarketDataProvider


def test_yahoo_provider_matches_exact_option_expiration_and_strike() -> None:
    requested_path = ""
    requested_date = ""
    expiration = date(2026, 8, 21)
    expiration_timestamp = int(datetime(2026, 8, 21, tzinfo=timezone.utc).timestamp())

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested_path, requested_date
        requested_path = request.url.path
        requested_date = request.url.params["date"]
        payload = {
            "optionChain": {
                "result": [{
                    "options": [{
                        "expirationDate": expiration_timestamp,
                        "puts": [{
                            "contractSymbol": "TQQQ260821P00050000",
                            "strike": 50,
                            "expiration": expiration_timestamp,
                            "bid": 0.45,
                            "ask": 0.50,
                            "lastPrice": 0.48,
                            "impliedVolatility": 0.62,
                            "lastTradeDate": int(datetime(2026, 7, 18, tzinfo=timezone.utc).timestamp()),
                        }],
                        "calls": [],
                    }],
                }],
                "error": None,
            }
        }
        return httpx.Response(200, content=json.dumps(payload))

    provider = YahooMarketDataProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    quote = provider.option_quote("TQQQ", "put", expiration, Decimal("50"))

    assert requested_path.endswith("/TQQQ")
    assert requested_date == str(expiration_timestamp)
    assert quote.contract_symbol == "TQQQ260821P00050000"
    assert quote.bid == Decimal("0.45")
    assert quote.ask == Decimal("0.5")
    assert quote.implied_volatility == Decimal("0.62")


def test_yahoo_provider_rejects_a_missing_contract() -> None:
    payload = {
        "optionChain": {
            "result": [{"options": [{"puts": [], "calls": []}]}],
            "error": None,
        }
    }
    provider = YahooMarketDataProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=json.dumps(payload))
            )
        )
    )

    try:
        provider.option_quote("TQQQ", "put", date(2026, 8, 21), Decimal("50"))
        assert False, "expected a missing-contract error"
    except Exception as error:
        assert "找不到" in str(error)
