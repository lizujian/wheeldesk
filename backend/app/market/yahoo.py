from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.domain.indicators import DailyBar
from app.market.base import (
    EarningsEvent,
    MarketCapitalization,
    MarketDataError,
    MarketSeries,
    OptionQuote,
    SessionQuote,
)

YAHOO_SYMBOLS = {"BRK.B": "BRK-B", "VIX": "^VIX"}


class YahooMarketDataProvider:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=10, headers={"User-Agent": "WheelDesk/0.1"})

    def daily_bars(self, symbol: str, limit: int = 300) -> MarketSeries:
        requested_symbol = symbol.upper()
        yahoo_symbol = YAHOO_SYMBOLS.get(requested_symbol, requested_symbol)
        try:
            response = self.client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}",
                params={"interval": "1d", "range": "2y", "events": "history"},
            )
            response.raise_for_status()
            data = response.json()
            bars = _parse_bars(data)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise MarketDataError(f"无法读取 {requested_symbol} 行情") from error
        if not bars:
            raise MarketDataError(f"{requested_symbol} 行情为空")
        return MarketSeries(symbol=requested_symbol, bars=bars[-limit:], source="yahoo")

    def session_quote(self, symbol: str) -> SessionQuote:
        requested_symbol = symbol.upper()
        yahoo_symbol = YAHOO_SYMBOLS.get(requested_symbol, requested_symbol)
        try:
            response = self.client.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}",
                params={
                    "interval": "1m",
                    "range": "1d",
                    "includePrePost": "true",
                },
            )
            response.raise_for_status()
            return _parse_session_quote(response.json(), requested_symbol)
        except MarketDataError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise MarketDataError(f"无法读取 {requested_symbol} 最新行情") from error

    def market_cap(self, symbol: str) -> MarketCapitalization:
        requested_symbol = symbol.upper()
        yahoo_symbol = YAHOO_SYMBOLS.get(requested_symbol, requested_symbol)
        today = date.today()
        period1 = int(
            datetime.combine(today - timedelta(days=550), time.min, tzinfo=timezone.utc).timestamp()
        )
        period2 = int(
            datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc).timestamp()
        )
        try:
            response = self.client.get(
                "https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/"
                f"{yahoo_symbol}",
                params={
                    "symbol": yahoo_symbol,
                    "type": "quarterlyMarketCap",
                    "period1": period1,
                    "period2": period2,
                },
                timeout=4,
            )
            response.raise_for_status()
            results = response.json()["timeseries"]["result"]
            records = [
                record
                for result in results
                for record in result.get("quarterlyMarketCap", [])
                if record.get("reportedValue", {}).get("raw") is not None
                and record.get("asOfDate")
            ]
            latest = max(records, key=lambda record: record["asOfDate"])
            return MarketCapitalization(
                symbol=requested_symbol,
                value=Decimal(str(latest["reportedValue"]["raw"])),
                currency=str(latest.get("currencyCode") or "").upper(),
                as_of=date.fromisoformat(latest["asOfDate"]),
                source="yahoo",
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise MarketDataError(f"无法读取 {requested_symbol} 公开市值") from error

    def option_quote(
        self,
        symbol: str,
        option_type: str,
        expiration: date,
        strike: Decimal,
    ) -> OptionQuote:
        requested_symbol = symbol.upper()
        yahoo_symbol = YAHOO_SYMBOLS.get(requested_symbol, requested_symbol)
        expiration_timestamp = int(
            datetime.combine(expiration, time.min, tzinfo=timezone.utc).timestamp()
        )
        try:
            response = self.client.get(
                f"https://query2.finance.yahoo.com/v7/finance/options/{yahoo_symbol}",
                params={"date": expiration_timestamp},
            )
            response.raise_for_status()
            return _parse_option_quote(
                response.json(), requested_symbol, option_type, expiration, strike
            )
        except MarketDataError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise MarketDataError(f"无法读取 {requested_symbol} 期权行情") from error

    def earnings_date(self, symbol: str) -> EarningsEvent:
        requested_symbol = symbol.upper()
        yahoo_symbol = YAHOO_SYMBOLS.get(requested_symbol, requested_symbol)
        try:
            response = self.client.get(
                f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{yahoo_symbol}",
                params={"modules": "calendarEvents"},
                timeout=4,
            )
            response.raise_for_status()
            result = response.json()["quoteSummary"]["result"][0]
            values = result["calendarEvents"]["earnings"]["earningsDate"]
            timestamps = [int(value["raw"]) for value in values if value.get("raw")]
            if not timestamps:
                raise MarketDataError(f"{requested_symbol} 暂无公开财报日期")
            next_date = min(
                datetime.fromtimestamp(timestamp, timezone.utc).date()
                for timestamp in timestamps
            )
            return EarningsEvent(
                symbol=requested_symbol,
                event_date=next_date,
                source="yahoo",
            )
        except MarketDataError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise MarketDataError(f"无法读取 {requested_symbol} 公开财报日期") from error


def _parse_bars(payload: dict[str, Any]) -> list[DailyBar]:
    chart = payload["chart"]
    if chart.get("error"):
        raise MarketDataError(str(chart["error"]))
    result = chart["result"][0]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    bars: list[DailyBar] = []
    for index, timestamp in enumerate(timestamps):
        values = [quote[field][index] for field in ("open", "high", "low", "close", "volume")]
        if any(value is None for value in values):
            continue
        bars.append(
            DailyBar(
                date=datetime.fromtimestamp(timestamp, timezone.utc).date(),
                open=Decimal(str(values[0])),
                high=Decimal(str(values[1])),
                low=Decimal(str(values[2])),
                close=Decimal(str(values[3])),
                volume=int(values[4]),
            )
        )
    return bars


def _parse_session_quote(payload: dict[str, Any], symbol: str) -> SessionQuote:
    chart = payload["chart"]
    if chart.get("error"):
        raise MarketDataError(str(chart["error"]))
    results = chart.get("result") or []
    if not results:
        raise MarketDataError(f"{symbol} 最新行情为空")
    result = results[0]
    timestamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    valid = [
        (int(timestamp), Decimal(str(close)))
        for timestamp, close in zip(timestamps, closes)
        if close is not None
    ]
    if not valid:
        raise MarketDataError(f"{symbol} 最新价格为空")
    timestamp, price = valid[-1]
    meta = result.get("meta") or {}
    previous = meta.get("chartPreviousClose", meta.get("previousClose"))
    if previous is None:
        raise MarketDataError(f"{symbol} 上一收盘价为空")
    periods = meta.get("currentTradingPeriod") or {}
    regular = periods.get("regular") or {}
    regular_start = int(regular.get("start", 0))
    regular_end = int(regular.get("end", 0))
    if regular_start and timestamp < regular_start:
        session = "pre"
    elif regular_end and timestamp > regular_end:
        session = "post"
    else:
        session = "regular"
    quoted_at = datetime.fromtimestamp(timestamp, timezone.utc)
    timezone_name = meta.get("exchangeTimezoneName") or "America/New_York"
    market_date = quoted_at.astimezone(ZoneInfo(timezone_name)).date()
    return SessionQuote(
        symbol=symbol,
        price=price,
        previous_close=Decimal(str(previous)),
        quoted_at=quoted_at,
        market_date=market_date,
        session=session,
        source="yahoo",
    )


def _parse_option_quote(
    payload: dict[str, Any],
    symbol: str,
    option_type: str,
    expiration: date,
    strike: Decimal,
) -> OptionQuote:
    chain = payload["optionChain"]
    if chain.get("error"):
        raise MarketDataError(str(chain["error"]))
    results = chain.get("result") or []
    if not results:
        raise MarketDataError(f"找不到 {symbol} 期权链")
    key = "puts" if option_type.lower() == "put" else "calls"
    options = results[0].get("options") or []
    contracts = options[0].get(key, []) if options else []
    for contract in contracts:
        if Decimal(str(contract.get("strike"))) != strike:
            continue
        contract_expiration = datetime.fromtimestamp(
            int(contract["expiration"]), timezone.utc
        ).date()
        if contract_expiration != expiration:
            continue
        quoted_at = datetime.fromtimestamp(
            int(contract["lastTradeDate"]), timezone.utc
        ).replace(tzinfo=None)
        return OptionQuote(
            contract_symbol=str(contract["contractSymbol"]),
            symbol=symbol,
            option_type=option_type.lower(),
            expiration=expiration,
            strike=strike,
            bid=Decimal(str(contract.get("bid", 0))),
            ask=Decimal(str(contract.get("ask", 0))),
            last=Decimal(str(contract.get("lastPrice", 0))),
            implied_volatility=Decimal(str(contract.get("impliedVolatility", 0))),
            quoted_at=quoted_at,
            source="yahoo",
        )
    raise MarketDataError(f"找不到 {symbol} {expiration} ${strike} {option_type}")
