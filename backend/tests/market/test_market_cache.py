from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import Base, MarketDataCache
from app.domain.indicators import DailyBar
from app.market.base import MarketSeries
from app.market.cache import MarketCache


def test_persistent_cache_preserves_decimals_dates_and_provider_boundaries(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cache.db'}")
    Base.metadata.create_all(engine)
    cache = MarketCache(engine, "endpoint-one")
    key = ("bars", "US.QQQ", 300, date.today())
    bar = DailyBar(date.today(), Decimal("100.01"), Decimal("101.01"), Decimal("99.01"), Decimal("100.01"), 123)
    cache.put(key, MarketSeries("QQQ", [bar], "ibkr"), 60)
    assert MarketCache(engine, "endpoint-one").get(key).bars == [bar]
    assert MarketCache(engine, "endpoint-two").get(key) is None
    with Session(engine) as session:
        row = session.scalar(select(MarketDataCache))
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
        session.commit()
    assert cache.get(key) is None
    engine.dispose()
