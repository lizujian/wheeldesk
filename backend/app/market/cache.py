"""Provider-specific daily/contract caches; no prices or advice relabelled."""
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math

from sqlalchemy.orm import Session

from app.db_models import MarketDataCache
from app.domain.indicators import DailyBar
from app.market.base import MarketSeries


class MarketCache:
    def __init__(self, engine, namespace: str):
        self.engine, self.namespace = engine, namespace

    def _key(self, key):
        return hashlib.sha256(f"{self.namespace}:{key!r}".encode()).hexdigest()

    def get(self, key):
        with Session(self.engine) as session:
            row = session.get(MarketDataCache, self._key(key))
            if row is None or row.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
                return None
            payload = row.payload
        if payload["type"] == "series":
            return MarketSeries(payload["symbol"], [DailyBar(date.fromisoformat(bar["date"]),
                *(Decimal(bar[field]) for field in ("open", "high", "low", "close")), int(bar["volume"]))
                for bar in payload["data"]], payload.get("source", "unknown"))
        return payload["data"]

    def put(self, key, value, ttl):
        if isinstance(value, MarketSeries):
            payload = {"type": "series", "symbol": value.symbol, "source": value.source, "data": [asdict(bar) for bar in value.bars]}
        else:
            payload = {"type": "records", "data": value}
        def clean(value):
            if isinstance(value, float) and not math.isfinite(value):
                return None
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items()}
            if isinstance(value, list):
                return [clean(item) for item in value]
            return value
        payload = json.loads(json.dumps(clean(payload), default=str, allow_nan=False))
        with Session(self.engine) as session:
            row = session.get(MarketDataCache, self._key(key))
            if row is None:
                row = MarketDataCache(key=self._key(key))
                session.add(row)
            row.payload = payload
            row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=ttl)
            session.commit()
