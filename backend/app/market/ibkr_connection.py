"""Bounded, read-only IBKR queries on one dedicated asyncio thread."""
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
import logging
from threading import Lock, Thread
from time import monotonic

from app.market.base import MarketDataError

ERRORS = {
    354: "未订阅该合约的 API 行情",
    10089: "该股票的 API 行情需要额外订阅，可尝试延迟行情",
    10090: "部分 API 行情未订阅",
    10091: "部分 API 行情需要额外订阅，可尝试延迟行情",
    10167: "未订阅实时行情，使用延迟行情",
    10168: "未订阅行情且延迟行情不可用",
    10197: "另一登录会话占用了行情，请检查盈透客户端",
    200: "合约不存在或未唯一匹配",
    162: "历史行情不可用或请求频率受限",
    326: "Client ID 已被其他连接使用，请修改设置",
    321: "API 请求被拒绝，请检查 Gateway 设置",
}


class IbkrConnection:
    def __init__(self, host, port, client_id=71):
        if client_id <= 0:
            raise ValueError("只读行情客户端必须使用非零 Client ID")
        self.host, self.port, self.client_id = host, port, client_id
        self._loop = asyncio.new_event_loop()
        self._thread = Thread(target=self._serve, daemon=True, name="ibkr-market")
        self._thread.start()
        self._lock = Lock()
        self._connection_lock = asyncio.Lock()
        self._snapshot_lock = asyncio.Lock()
        self._read_slots = asyncio.Semaphore(6)
        self._ib = None
        self._retry_after = 0.0
        self._errors = {}
        self._closed = False

    def _serve(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        self._loop.close()

    async def _connect(self):
        async with self._connection_lock:
            return await self._connect_once()

    async def _connect_once(self):
        if self._ib is not None and self._ib.isConnected():
            return self._ib
        if monotonic() < self._retry_after:
            raise MarketDataError("IB Gateway 暂不可用，请检查登录状态后重试")
        from ib_async import IB, StartupFetch
        # SDK logs can contain account identifiers; public errors use codes only.
        logging.getLogger("ib_async").setLevel(logging.CRITICAL)
        ib = IB()
        def on_error(req_id, code, message, contract):
            if code in ERRORS:
                self._errors[getattr(contract, "conId", 0)] = code
        ib.errorEvent += on_error
        try:
            await ib.connectAsync(self.host, self.port, clientId=self.client_id,
                                  timeout=8, readonly=True, fetchFields=StartupFetch(0))
        except Exception as error:
            ib.disconnect()
            self._retry_after = monotonic() + 5
            raise MarketDataError("无法连接 IB Gateway，请检查地址、端口、Client ID 和登录状态") from error
        self._ib = ib
        return ib

    def call(self, method, **kwargs):
        if method not in {"details", "history", "iv_history", "snapshots", "diagnostics", "positions"}:
            raise MarketDataError("此连接仅支持持仓与行情只读查询")
        with self._lock:
            if self._closed:
                raise MarketDataError("IBKR 行情连接已关闭，请重试")
            future = asyncio.run_coroutine_threadsafe(self._query(method, kwargs), self._loop)
        try:
            return future.result(timeout=40)
        except FutureTimeout as error:
            future.cancel()
            raise MarketDataError("IBKR 行情请求超时，请稍后刷新") from error
        except MarketDataError:
            raise
        except Exception as error:
            raise MarketDataError("IBKR 行情查询失败，请检查 Gateway 连接及 API 行情权限") from error

    async def _query(self, method, kwargs):
        async with self._read_slots:
            return await self._query_once(method, kwargs)

    async def _query_once(self, method, kwargs):
        ib = await self._connect()
        if method == "details":
            return await asyncio.wait_for(ib.reqContractDetailsAsync(kwargs["contract"]), 12)
        if method == "history":
            return await ib.reqHistoricalDataAsync(kwargs["contract"], endDateTime="",
                durationStr="2 Y", barSizeSetting="1 day",
                whatToShow="TRADES" if kwargs["contract"].secType == "IND" else "ADJUSTED_LAST",
                useRTH=True, formatDate=2, timeout=25)
        if method == "iv_history":
            return await ib.reqHistoricalDataAsync(kwargs["contract"], endDateTime="",
                durationStr="1 M", barSizeSetting="1 day", whatToShow="OPTION_IMPLIED_VOLATILITY",
                useRTH=True, formatDate=2, timeout=15)
        if method == "positions":
            positions = await asyncio.wait_for(ib.reqPositionsAsync(), 8)
            return [{"contract": p.contract, "quantity": p.position} for p in positions]
        if method == "diagnostics":
            return {"connected": True, "client_readonly": True,
                    "gateway_readonly": "请在 Gateway 的 API 设置中确认只读 API 已勾选",
                    "server_version": str(ib.client.serverVersion()),
                    "positions_count": len([p for p in ib.positions() if p.position]), "vix_provider": "ibkr"}
        async with self._snapshot_lock:
            return await self._snapshots(ib, kwargs)

    async def _snapshots(self, ib, kwargs):
        # Query on demand. Brief subscriptions are always cancelled; no timers
        # or long-running streaming subscriptions survive the refresh request.
        from datetime import datetime, timezone
        import math
        def valid(value):
            return isinstance(value, (float, int)) and math.isfinite(value) and value > 0
        def usable(ticker):
            c = ticker.contract
            prices = (valid(ticker.bid) and valid(ticker.ask) if c.secType == "OPT"
                      else valid(ticker.last) and (valid(ticker.close) or c.exchange == "OVERNIGHT"))
            return prices and ticker.time is not None and ticker.marketDataType in {1, 2, 3, 4}
        result = {}
        pending = list(kwargs["contracts"])
        for contract in pending:
            self._errors.pop(contract.conId, None)
        for market_type in (3, 2, 4):  # delayed/live, entitled frozen, delayed frozen
            if not pending:
                break
            ib.reqMarketDataType(market_type)
            tickers = []
            try:
                for contract in pending:
                    ticker = ib.reqMktData(contract, "", False, False)
                    # ib_async reuses Ticker objects; reset cached fields so a
                    # new request cannot re-label an old quote as current.
                    ticker.marketDataType = 0
                    ticker.bid = ticker.ask = ticker.last = ticker.close = float("nan")
                    ticker.time = ticker.rtTime = None
                    ticker.lastTimestamp = ticker.delayedLastTimestamp = None
                    ticker.modelGreeks = None
                    tickers.append(ticker)
                if hasattr(ib, "updateEvent"):
                    deadline = monotonic() + 2.5
                    while monotonic() < deadline and not all(usable(ticker) for ticker in tickers):
                        try:
                            await asyncio.wait_for(ib.updateEvent, deadline - monotonic())
                        except asyncio.TimeoutError:
                            break
                    # Allow last-trade timestamps in the same response burst to settle.
                    await asyncio.sleep(.1)
                else:
                    await asyncio.sleep(2.5)
                fetched = datetime.now(timezone.utc)
                remaining = []
                for ticker in tickers:
                    c = ticker.contract
                    if not usable(ticker):
                        remaining.append(c)
                        continue
                    trade_time = ticker.delayedLastTimestamp if ticker.marketDataType in {3, 4} else ticker.lastTimestamp
                    result[c.conId] = {"bid": ticker.bid, "ask": ticker.ask,
                        "last": ticker.last, "close": ticker.close,
                        "market_data_type": ticker.marketDataType,
                        "fetched_at": fetched, "market_as_of": (trade_time or ticker.rtTime) if c.secType != "OPT" else ticker.rtTime,
                        "iv": getattr(ticker.modelGreeks, "impliedVol", None)}
                pending = remaining
            finally:
                for ticker in tickers:
                    ib.cancelMktData(ticker.contract)
        return result

    def error_for(self, con_id, *, sec_type=""):
        code = self._errors.get(con_id)
        if code in {354, 10089, 10090, 10091, 10167, 10168}:
            prices = "期权买卖价" if sec_type == "OPT" else "报价"
            permission = "美国期权 OPRA 的 API 行情权限" if sec_type == "OPT" else "该合约的 API 行情权限"
            retry = "期权常规交易时段外可能无买卖价，请在开盘后重新加载页面进行全量刷新；若仍失败，" if sec_type == "OPT" else ""
            return (f"IBKR {code}：已尝试延迟及收市行情，仍无可用{prices}；"
                    f"{retry}请检查{permission}，保留上次估值")
        return f"IBKR {code}：{ERRORS[code]}" if code else "IBKR 未返回可用报价，保留上次估值"

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            async def disconnect():
                if self._ib is not None:
                    self._ib.disconnect()
            asyncio.run_coroutine_threadsafe(disconnect(), self._loop).result(timeout=3)
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)
