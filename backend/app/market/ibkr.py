"""IB Gateway quotes; contract IDs are verified independently of ledger IDs."""
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from threading import RLock
from time import monotonic
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ib_async import Index, Option, Stock

from app.domain.indicators import DailyBar
from app.market.base import (ImpliedVolatilityComparison, ImpliedVolatilityPoint,
                             MarketDataError, MarketSeries, OptionQuote, SessionQuote)

NY = ZoneInfo("America/New_York")
UTC = timezone.utc
REFRESH_CACHE_KINDS = {"quote", "iv", "context_history"}


def broker_symbol(symbol):
    return {"BRK.B": "BRK B", "BRK-B": "BRK B"}.get(symbol.upper(), symbol.upper())


def number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


class IbkrMarketDataProvider:
    def __init__(self, connection, cache=None, now=None):
        self.connection, self._persistent = connection, cache
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._fetch_locks = {}
        self._quote_lock = RLock()
        self._cache = {}
        self._warnings = {}

    def begin_refresh(self):
        with self._lock:
            self._cache = {key: value for key, value in self._cache.items() if key[0] not in REFRESH_CACHE_KINDS}
            self._warnings.clear()

    def _cached(self, key, ttl, fetch, persistent=False):
        with self._lock:
            key_lock = self._fetch_locks.setdefault(key, RLock())
        with key_lock:
            with self._lock:
                cached = self._cache.get(key)
                if cached and monotonic() - cached[0] < ttl:
                    if isinstance(cached[1], MarketDataError):
                        raise cached[1]
                    return cached[1]
            value = self._persistent.get(key) if persistent and self._persistent else None
            if value is None:
                try:
                    value = fetch()
                except MarketDataError as error:
                    with self._lock:
                        # Prefetch and consumers share failures for this refresh.
                        # begin_refresh clears them so the next attempt retries.
                        failed_at = monotonic() if key[0] in REFRESH_CACHE_KINDS else monotonic() - ttl + 5
                        self._cache[key] = (failed_at, error)
                    raise
                if persistent and self._persistent:
                    self._persistent.put(key, value, ttl)
            with self._lock:
                self._cache[key] = (monotonic(), value)
            return value

    def _instrument(self, symbol, exchange="SMART"):
        is_vix = symbol.upper() in {"VIX", "^VIX"}
        key = ("index" if is_vix else "stock", "VIX" if is_vix else broker_symbol(symbol), "CBOE" if is_vix else exchange)
        def fetch():
            contract = Index("VIX", "CBOE", "USD") if is_vix else Stock(key[1], exchange, "USD")
            details = self.connection.call("details", contract=contract)
            matches = {d.contract.conId: d for d in details if d.contract.symbol == key[1]
                       and d.contract.conId > 0 and d.contract.currency == "USD"
                       and d.contract.secType == ("IND" if is_vix else "STK")
                       and (not is_vix or d.contract.exchange == "CBOE")
                       and (exchange != "OVERNIGHT" or d.contract.exchange == "OVERNIGHT")}
            if len(matches) != 1:
                raise MarketDataError(f"{symbol} 未唯一匹配 IBKR {'CBOE 指数' if is_vix else '美股'}合约")
            return next(iter(matches.values()))
        return self._cached(key, 86400, fetch)

    def _option(self, symbol, option_type, expiration, strike):
        if option_type.lower() not in {"call", "put"}:
            raise MarketDataError("期权类型必须为 Call 或 Put")
        if expiration < self._now().astimezone(NY).date():
            raise MarketDataError("已到期期权保留历史记录，不查询当前行情")
        right = "C" if option_type.lower() == "call" else "P"
        underlying = broker_symbol(symbol)
        key = ("option", underlying, right, expiration, strike)
        def fetch():
            requested = Option(underlying, expiration.strftime("%Y%m%d"), float(strike), right,
                               "SMART", multiplier="100", currency="USD", tradingClass=underlying)
            details = self.connection.call("details", contract=requested)
            matches = {d.contract.conId: d for d in details
                       if d.contract.secType == "OPT" and d.contract.symbol == underlying
                       and d.contract.right == right and number(d.contract.strike) == strike
                       and d.contract.lastTradeDateOrContractMonth[:8] == expiration.strftime("%Y%m%d")
                       and d.contract.multiplier == "100" and d.contract.currency == "USD"
                       and d.contract.tradingClass == underlying}
            if len(matches) != 1:
                raise MarketDataError(f"{symbol} {expiration} ${strike} {option_type} 未唯一匹配标准 IBKR 合约")
            return next(iter(matches.values()))
        return self._cached(key, 86400, fetch)

    def _prefetch(self, contracts):
        with self._quote_lock:
            with self._lock:
                missing = [c for c in {(c.conId, c.exchange): c for c in contracts}.values()
                           if not self._cache.get(("quote", c.conId, c.exchange)) or monotonic() - self._cache[("quote", c.conId, c.exchange)][0] >= 300]
            while missing:
                batch, remaining, used = [], [], set()
                for contract in missing:
                    if contract.conId in used or len(batch) >= 40:
                        remaining.append(contract)
                    else:
                        batch.append(contract)
                        used.add(contract.conId)
                values = self.connection.call("snapshots", contracts=batch)
                with self._lock:
                    for c in batch:
                        value = values.get(c.conId) or MarketDataError(self.connection.error_for(c.conId))
                        self._cache[("quote", c.conId, c.exchange)] = (monotonic(), value)
                missing = remaining

    def prefetch_quotes(self, symbols, options):
        from concurrent.futures import ThreadPoolExecutor
        def stock_contracts(symbol):
            try:
                details = self._instrument(symbol)
                return [details.contract, self._active_details(details).contract]
            except MarketDataError:
                return []
        def option_contract(contract):
            try:
                return [self._option(*contract).contract]
            except MarketDataError:
                return []
        with ThreadPoolExecutor(max_workers=6) as executor:
            contracts = [c for group in executor.map(stock_contracts, sorted(set(symbols))) for c in group]
            contracts.extend(c for group in executor.map(option_contract, dict.fromkeys(options)) for c in group)
        self._prefetch(contracts)

    def prefetch_snapshots(self, symbols):
        contracts = []
        for symbol in sorted(set(symbols)):
            try:
                details = self._instrument(symbol)
                contracts.append(details.contract)
                contracts.append(self._active_details(details).contract)
            except MarketDataError:
                pass
        self._prefetch(contracts)

    def prefetch_options(self, contracts):
        requested = []
        for contract in dict.fromkeys(contracts):
            try:
                requested.append(self._option(*contract).contract)
            except MarketDataError:
                pass
        self._prefetch(requested)

    def _snapshot(self, contract):
        self._prefetch([contract])
        with self._lock:
            value = self._cache[("quote", contract.conId, contract.exchange)][1]
            if isinstance(value, MarketDataError):
                raise value
            return value

    def _session(self, details, at=None):
        now = at or self._now()
        try:
            if details.contract.exchange == "OVERNIGHT":
                return "overnight" if any(s.start <= now < s.end for s in details.tradingSessions()) else "closed"
            for session in details.liquidSessions():
                if session.start <= now < session.end:
                    return "regular"
            for session in details.tradingSessions():
                if session.start <= now < session.end:
                    return "pre" if now.astimezone(NY).time() < time(9, 30) else "post"
        except (ValueError, AttributeError, ZoneInfoNotFoundError):
            pass
        return "closed"

    def _active_details(self, details):
        now = self._now().astimezone(NY)
        if (details.contract.secType == "STK" and self._session(details) == "closed"
                and (now.hour >= 18 or now.hour < 4)
                and "OVERNIGHT" in getattr(details, "validExchanges", "").split(",")):
            try:
                overnight = self._instrument(details.contract.symbol, "OVERNIGHT")
                if self._session(overnight) == "overnight":
                    return overnight
            except MarketDataError:
                pass
        return details

    def _extended_reference_close(self, symbol, regular_details):
        now = self._now()
        today = now.astimezone(NY).date()
        try:
            today_complete = any(s.end.astimezone(NY).date() == today and s.end <= now
                                 for s in regular_details.liquidSessions())
        except (AttributeError, ValueError, ZoneInfoNotFoundError):
            today_complete = False
        series = self._daily_series(symbol, include_today=True)
        bars = [bar for bar in series.bars if bar.date < today or (bar.date == today and today_complete)]
        if not bars:
            raise MarketDataError(f"{symbol} 缺少可用于盘外涨跌幅的正常时段收盘价")
        return bars[-1].close

    def _daily_series(self, symbol, *, include_today=False):
        today = self._now().astimezone(NY).date()
        def fetch():
            rows = self.connection.call("history", contract=self._instrument(symbol).contract)
            bars = {}
            for row in rows:
                day = row.date.date() if isinstance(row.date, datetime) else row.date
                if isinstance(day, str):
                    day = date.fromisoformat(day[:10])
                prices = [number(getattr(row, field)) for field in ("open", "high", "low", "close")]
                if day > today or (day == today and not include_today) or any(value is None for value in prices):
                    continue
                bars[day] = DailyBar(day, *prices, int(row.volume))
            if not bars:
                raise MarketDataError(f"{symbol} IBKR 未返回有效完成日线")
            return MarketSeries(symbol, [bars[day] for day in sorted(bars)], "ibkr")
        return self._cached(("context_history" if include_today else "history", symbol, today),
                            300 if include_today else 3600, fetch, persistent=not include_today)

    def vix_history(self):
        # Today's high is useful for the 52-week range, but not a completed close.
        return self._daily_series("VIX", include_today=True)

    def daily_bars(self, symbol, limit=300):
        today = self._now().astimezone(NY).date()
        def fetch():
            series = self._daily_series(symbol)
            if len(series.bars) < limit:
                raise MarketDataError(f"{symbol} IBKR 完成日线不足 {limit} 条")
            return MarketSeries(symbol, series.bars[-limit:], series.source)
        return self._cached(("bars", symbol, limit, today), 3600, fetch, persistent=True)

    def watchlist_bars(self, symbol, limit=300):
        # Newly listed ETFs can show RSI and IV before they have 200/300 bars.
        series = self._daily_series(symbol)
        return MarketSeries(symbol, series.bars[-limit:], series.source)

    def session_quote(self, symbol):
        try:
            details = self._instrument(symbol)
            regular_details = details
            active = self._active_details(details)
            market_session = self._session(active)
            session_error = None
            try:
                row = self._snapshot(active.contract)
                details = active
            except MarketDataError as error:
                if active.contract.exchange != "OVERNIGHT":
                    raise
                session_error = f"夜盘暂未取得有效报价：{error}"
                row = self._snapshot(details.contract)
            price, previous = number(row["last"]), number(row["close"])
            if details.contract.secType == "STK" and market_session in {"post", "overnight"}:
                try:
                    previous = self._extended_reference_close(symbol, regular_details)
                except MarketDataError:
                    # The price can still be shown; do not invent a change baseline.
                    previous = Decimal(0)
            if price is None or previous is None:
                raise MarketDataError(f"{symbol} IBKR 报价缺失")
            session = self._session(details, row["market_as_of"]) if row["market_as_of"] else "unknown"
            quality = {1: "realtime", 2: "closed", 3: "delayed", 4: "delayed"}.get(row["market_data_type"], "unknown")
            if quality == "realtime" and (session != "regular" or market_session != "regular"):
                quality = "unknown"
            fetched = row["fetched_at"]
            self._warnings.pop(symbol, None)
            return SessionQuote(symbol, price, previous, row["market_as_of"] or fetched,
                fetched.astimezone(NY).date(), session, "ibkr", quality, fetched, row["market_as_of"],
                market_session, details.contract.exchange, session_error)
        except MarketDataError as error:
            self._warnings[symbol] = f"{symbol} IBKR 报价不可用：{error}"
            raise

    def implied_volatility(self, symbol):
        """Underlying daily IV, independent of any held option's expiry/strike."""
        def fetch():
            details = self._instrument(symbol)
            if details.contract.secType != "STK":
                raise MarketDataError(f"{symbol} 不支持标的历史 IV 查询")
            now = self._now()
            today = now.astimezone(NY).date()
            try:
                opened_today = any(s.start.astimezone(NY).date() == today and s.start <= now
                                   for s in details.liquidSessions())
            except (ValueError, AttributeError, ZoneInfoNotFoundError):
                opened_today = False
            rows = self.connection.call("iv_history", contract=details.contract)
            values = {}
            for row in rows:
                day = row.date.date() if isinstance(row.date, datetime) else row.date
                if isinstance(day, str):
                    day = date.fromisoformat(day[:10])
                value = number(row.close)
                if value is None or day > today or (day == today and not opened_today):
                    continue
                values[day] = value
            days = sorted(values)
            if not days:
                raise MarketDataError(f"{symbol} IBKR 未返回有效的标的历史 IV")
            latest = ImpliedVolatilityPoint(days[-1], values[days[-1]])
            previous = ImpliedVolatilityPoint(days[-2], values[days[-2]]) if len(days) > 1 else None
            return ImpliedVolatilityComparison(symbol, latest, previous,
                latest.value / previous.value - 1 if previous else None, "ibkr", self._now())
        return self._cached(("iv", symbol), 300, fetch)

    def option_quote(self, symbol, option_type, expiration, strike):
        details = self._option(symbol, option_type, expiration, strike)
        row = self._snapshot(details.contract)
        bid, ask = number(row["bid"]), number(row["ask"])
        if bid is None or ask is None or ask < bid:
            raise MarketDataError("IBKR 期权买卖价缺失或异常，保留上次估值")
        quality = {1: "realtime", 2: "closed", 3: "delayed", 4: "delayed"}.get(row["market_data_type"], "unknown")
        if self._session(details) != "regular" and quality == "realtime":
            quality = "closed"
        fetched = row["fetched_at"]
        return OptionQuote(details.contract.localSymbol, symbol, option_type, expiration, strike,
            bid, ask, number(row["last"]) or Decimal(0), number(row["iv"]), fetched,
            "ibkr", quality, fetched, None)

    def market_cap(self, symbol):
        raise MarketDataError("万亿俱乐部由用户维护，不查询市值")

    def earnings_date(self, symbol):
        raise MarketDataError("IBKR 财报日历暂不可用，请手动核对财报日期")

    def warnings(self):
        return [{"symbol": symbol, "error": message} for symbol, message in sorted(self._warnings.items())]

    def diagnostics(self):
        result = self.connection.call("diagnostics")
        self.prefetch_snapshots(["QQQ", "VIX"])
        for symbol in ("QQQ", "VIX"):
            try:
                quote = self.session_quote(symbol)
                result[symbol.lower()] = {"price": quote.price, "source": quote.source, "quality": quote.quality,
                                 "market_as_of": quote.market_as_of, "fetched_at": quote.fetched_at}
            except MarketDataError as error:
                result["quote_error"] = str(error)
        result["warnings"] = self.warnings()
        return result
