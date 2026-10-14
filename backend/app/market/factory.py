from threading import RLock

from app.market.ibkr import IbkrMarketDataProvider
from app.market.ibkr_connection import IbkrConnection
from app.market.settings import MarketSettings
from app.market.cache import MarketCache
from app.market.base import MarketDataError

_lock = RLock()
_providers = {}
def market_provider(settings: MarketSettings, engine=None):
    if not settings.configured:
        raise MarketDataError("请先在设置中配置 IB Gateway 地址和端口，并启动、登录 Gateway")
    with _lock:
        key = (settings.config_key, id(engine))
        if key not in _providers:
            cache = MarketCache(engine, settings.config_key) if engine is not None else None
            _providers[key] = IbkrMarketDataProvider(IbkrConnection(settings.ibkr_host, settings.ibkr_port, settings.ibkr_client_id), cache=cache)
        return _providers[key]


def close_providers():
    with _lock:
        for provider in _providers.values():
            provider.connection.close()
        _providers.clear()
