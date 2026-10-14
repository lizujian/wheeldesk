import asyncio
from concurrent.futures import ThreadPoolExecutor

import ib_async
import pytest

from app.market.base import MarketDataError
from app.market.ibkr_connection import IbkrConnection


class ErrorEvent:
    def __iadd__(self, handler):
        return self


class Client:
    def __init__(self):
        self.connected = False
        self.errorEvent = ErrorEvent()

    def isConnected(self):
        return self.connected

    async def connectAsync(self, host, port, **kwargs):
        assert kwargs["readonly"] is True and kwargs["clientId"] != 0
        await asyncio.sleep(.01)
        self.connected = True

    async def reqContractDetailsAsync(self, contract):
        return [contract]

    def disconnect(self):
        self.connected = False


def test_next_queries_reconnect_once_after_api_disconnect_even_when_refresh_is_parallel(monkeypatch):
    clients = []
    def create_client():
        client = Client()
        clients.append(client)
        return client
    monkeypatch.setattr(ib_async, "IB", create_client)
    connection = IbkrConnection("unused", 4001)
    try:
        assert connection.call("details", contract="QQQ") == ["QQQ"]
        clients[0].disconnect()
        with ThreadPoolExecutor(max_workers=6) as pool:
            assert list(pool.map(lambda symbol: connection.call("details", contract=symbol), range(6))) == [[symbol] for symbol in range(6)]
        assert len(clients) == 2
        assert clients[1].isConnected()
    finally:
        connection.close()


def test_failed_reconnect_waits_five_seconds_before_next_attempt_then_recovers(monkeypatch):
    now = [0]
    attempts = []
    class RecoveringClient(Client):
        async def connectAsync(self, *args, **kwargs):
            attempts.append(now[0])
            if now[0] < 5:
                raise ConnectionError("Gateway unavailable")
            await super().connectAsync(*args, **kwargs)
    monkeypatch.setattr(ib_async, "IB", RecoveringClient)
    monkeypatch.setattr("app.market.ibkr_connection.monotonic", lambda: now[0])
    connection = IbkrConnection("unused", 4001)
    try:
        with pytest.raises(MarketDataError, match="无法连接 IB Gateway"):
            connection.call("details", contract="QQQ")
        now[0] = 2
        with pytest.raises(MarketDataError, match="暂不可用"):
            connection.call("details", contract="QQQ")
        assert attempts == [0]
        now[0] = 6
        assert connection.call("details", contract="QQQ") == ["QQQ"]
        assert attempts == [0, 6]
    finally:
        connection.close()
