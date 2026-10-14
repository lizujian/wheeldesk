from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.market import get_market_provider, get_option_provider, get_vix_provider
from app.db import get_session
from app.db_models import (
    Base, MarketDataSettings, PositionRecord, UnmanagedPositionRecord,
    WheelCallLot, WheelPutLot, WheelRound, WheelShareLot,
)
from app.domain.indicators import DailyBar
from app.main import app
from app.market.base import (
    ImpliedVolatilityComparison, ImpliedVolatilityPoint, MarketDataError,
    MarketSeries, OptionQuote, SessionQuote,
)

DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 15, tzinfo=timezone.utc)
OLD = datetime(2026, 10, 13, 20)


class ScopeProvider:
    def __init__(self):
        self.spot = Decimal(500)
        self.generation = 0
        self.fail_history = False
        self.stock_batches = []
        self.option_batches = []
        self.option_requests = []
        self.iv_requests = []

    def begin_refresh(self):
        self.generation += 1

    def prefetch_snapshots(self, symbols):
        self.stock_batches.append(set(symbols))

    def prefetch_options(self, contracts):
        self.option_batches.append(list(contracts))

    def daily_bars(self, symbol, limit=300):
        if self.fail_history and symbol == "QQQ":
            raise MarketDataError("QQQ history unavailable")
        close = Decimal(18) if symbol == "VIX" else Decimal(500)
        bars = [DailyBar(DAY - timedelta(days=i), close, close + 1, close - 1, close, 1000)
                for i in range(400, 0, -1)]
        return MarketSeries(symbol, bars[-limit:], "ibkr")

    def session_quote(self, symbol):
        price = Decimal(19) if symbol == "VIX" else self.spot
        return SessionQuote(symbol, price, price - 1, NOW, DAY, "regular", "ibkr", "delayed", NOW)

    def vix_history(self):
        return self.daily_bars("VIX", 400)

    def implied_volatility(self, symbol):
        self.iv_requests.append(symbol)
        latest = Decimal("0.30") + Decimal(self.generation) / 100
        return ImpliedVolatilityComparison(
            symbol, ImpliedVolatilityPoint(DAY, latest),
            ImpliedVolatilityPoint(DAY - timedelta(days=1), Decimal("0.30")),
            latest / Decimal("0.30") - 1, "ibkr", NOW,
        )

    def option_quote(self, symbol, option_type, expiration, strike):
        self.option_requests.append((symbol, option_type, expiration, strike))
        return OptionQuote("test", symbol, option_type, expiration, strike,
                           Decimal(20), Decimal(21), Decimal("20.5"), Decimal("0.25"),
                           NOW, "ibkr", "closed", NOW)


class CombinedScopeProvider(ScopeProvider):
    def prefetch_quotes(self, symbols, contracts):
        self.stock_batches.append(set(symbols))
        self.option_batches.append(list(contracts))


def seed_holdings(session):
    metadata = dict(quote_source="ibkr", quote_vendor="ibkr", quote_quality="delayed",
                    quote_fetched_at=OLD, quote_market_as_of=OLD - timedelta(minutes=15))
    quotes = dict(**metadata, quote_bid=3, quote_ask=4, quote_last=Decimal("3.5"),
                  quote_iv=Decimal("0.2"), quote_as_of=OLD)
    long = PositionRecord(bucket="leaps", symbol="QQQ", asset_type="option", direction="long",
                          option_type="call", quantity=1, multiplier=100, entry_price=100,
                          current_price=110, opened_on=DAY - timedelta(days=60),
                          expiration=DAY + timedelta(days=700), strike=400, tranche=1,
                          peak_bid=115, last_error="previous option warning", **quotes)
    core = PositionRecord(bucket="core", symbol="BRK.B", asset_type="equity", quantity=2,
                          entry_price=400, current_price=400, opened_on=DAY)
    session.add_all([long, core, MarketDataSettings(id=1, club_symbols=["AAPL"])])
    session.flush()
    short = UnmanagedPositionRecord(
        category="pmcc", linked_position_id=long.id, symbol="QQQ", asset_type="option",
        direction="short", option_type="call", quantity=1, multiplier=100, entry_price=5,
        current_price=4, opened_on=DAY - timedelta(days=60), expiration=DAY + timedelta(days=120),
        strike=530, quote_as_of=OLD.date(), last_error="previous option warning", **metadata,
    )
    other = UnmanagedPositionRecord(
        symbol="AAPL", asset_type="option", direction="long", option_type="put",
        quantity=1, multiplier=100, entry_price=10, current_price=8, opened_on=DAY,
        expiration=DAY + timedelta(days=90), strike=450, quote_as_of=OLD.date(),
        last_error="previous option warning", **metadata,
    )
    stock = UnmanagedPositionRecord(symbol="AAPL", asset_type="equity", quantity=10,
                                     entry_price=400, current_price=400, opened_on=DAY)
    wheel_round = WheelRound(number=1, opened_on=DAY)
    session.add_all([short, other, stock, wheel_round])
    session.flush()
    put = WheelPutLot(round_id=wheel_round.id, symbol="TQQQ", batch_number=1, trade_date=DAY,
                      expiration=DAY + timedelta(days=45), strike=60, premium=5, quantity=1,
                      open_quantity=1, entry_tqqq_price=65, captured_fraction=Decimal("0.2"),
                      early_close_message="previous estimate", **quotes)
    session.add(put)
    session.flush()
    share = WheelShareLot(put_lot_id=put.id, assigned_on=DAY, assignment_strike=60,
                           original_quantity=100, remaining_quantity=100)
    session.add(share)
    session.flush()
    call = WheelCallLot(share_lot_id=share.id, trade_date=DAY, expiration=DAY + timedelta(days=45),
                        strike=70, premium=5, quantity=1, **quotes)
    session.add(call)
    session.commit()


def option_state(sessions):
    with sessions() as session:
        result = {}
        for model in (PositionRecord, UnmanagedPositionRecord, WheelPutLot, WheelCallLot):
            query = select(model)
            if model in (PositionRecord, UnmanagedPositionRecord):
                query = query.where(model.asset_type == "option")
            for record in session.scalars(query):
                result[(model.__name__, record.id)] = {
                    column.name: getattr(record, column.name) for column in model.__table__.columns
                }
        return result


@contextmanager
def scoped_client(combined):
    engine = create_engine("sqlite+pysqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    provider = CombinedScopeProvider() if combined else ScopeProvider()

    def override_session():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    for dependency in (get_market_provider, get_option_provider, get_vix_provider):
        app.dependency_overrides[dependency] = lambda: provider
    try:
        with TestClient(app) as client:
            response = client.post("/api/portfolio/initialize", json={
                "age": 36, "opening_equity": 100000, "opening_date": DAY.isoformat(),
            })
            assert response.status_code == 201, response.text
            with sessions() as session:
                seed_holdings(session)
            yield client, provider, sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize("fail_history", [False, True])
def test_stock_refresh_preserves_all_option_state_even_when_history_fails(combined, fail_history):
    with scoped_client(combined) as (client, provider, sessions):
        before = option_state(sessions)
        provider.fail_history = fail_history
        for spot in (Decimal(500), Decimal(540)):
            provider.spot = spot
            response = client.post("/api/market/refresh?scope=stocks")
            assert response.status_code == (503 if fail_history else 200), response.text
            assert option_state(sessions) == before
            assert provider.option_requests == []
            assert provider.iv_requests == []
            assert all(not batch for batch in provider.option_batches)
            assert {"QQQ", "DRAM", "SOXX", "VIX", "AAPL", "BRK.B"} <= provider.stock_batches[-1]
            with sessions() as session:
                assert session.scalar(select(PositionRecord).where(PositionRecord.asset_type == "equity")).current_price == spot
                assert session.scalar(select(UnmanagedPositionRecord).where(UnmanagedPositionRecord.asset_type == "equity")).current_price == spot
            if fail_history:
                continue
            payload = response.json()
            assert payload["refresh_scope"] == "stocks"
            assert payload["vix_context"]["price"] == 19
            qqq = next(row for row in payload["leaps_watchlist"] if row["symbol"] == "QQQ")
            assert qqq["price"] == spot
            assert qqq["ma200"] == 500
            assert qqq["iv"] is None
            assert qqq["iv_error"] == "IV 仅在全量刷新时更新"
            assert "holding_occupancy" not in qqq
            pmcc = payload["pmcc"]["states"][0]
            assert pmcc["underlying_price"] == spot
            assert pmcc["assignment_risk"] == (spot >= 530)
            assert pmcc["coverage_ratio"] == 1
            assert pmcc["long_debit"] == 10000
            assert pmcc["long_current_value"] == 11000
            assert pmcc["short_current_value"] == 400


@pytest.mark.parametrize("combined", [False, True])
@pytest.mark.parametrize("query", ["?scope=full", ""])
def test_full_refresh_and_legacy_endpoint_update_every_option_model(combined, query):
    with scoped_client(combined) as (client, provider, sessions):
        response = client.post(f"/api/market/refresh{query}")
        assert response.status_code == 200, response.text
        assert response.json()["refresh_scope"] == "full"
        assert len(provider.option_batches[-1]) == 5
        assert len(provider.option_requests) == 5
        assert set(provider.iv_requests) == {"QQQ", "DRAM", "SOXX", "AAPL"}
        assert all(row["iv"] for row in response.json()["leaps_watchlist"])
        rows = {row["symbol"]: row for row in response.json()["leaps_watchlist"]}
        assert rows["QQQ"]["holding_occupancy"] == {"committed": 10000, "net_cash_flow": -1600}
        assert rows["AAPL"]["holding_occupancy"] is None
        assert rows["SOXX"]["holding_occupancy"] is None
        after = option_state(sessions)
        for (model, _), values in after.items():
            assert values["quote_fetched_at"] == NOW.replace(tzinfo=None)
            assert values["quote_quality"] == "closed"
            if model == "PositionRecord":
                assert values["current_price"] == 20
                assert values["quote_bid"] == 20
                assert values["last_error"] is None
            elif model == "UnmanagedPositionRecord":
                assert values["current_price"] == (21 if values["direction"] == "short" else 20)
                assert values["last_error"] is None
            else:
                assert values["quote_bid"] == 20
                assert values["quote_ask"] == 21


def test_invalid_refresh_scope_is_rejected_without_changing_holdings():
    with scoped_client(True) as (client, provider, sessions):
        before = option_state(sessions)
        response = client.post("/api/market/refresh?scope=unknown")
        assert response.status_code == 422
        assert option_state(sessions) == before
        assert provider.generation == 0


def test_full_refresh_aggregates_occupancy_by_symbol_from_open_pmcc_longs():
    with scoped_client(True) as (client, provider, sessions):
        with sessions() as session:
            for symbol, quantity, entry, status in (
                ("QQQ", 2, Decimal(50), "open"),
                ("DRAM", 1, Decimal("10.68"), "open"),
                ("DRAM", 1, Decimal(999), "closed"),
            ):
                session.add(PositionRecord(
                    bucket="leaps", symbol=symbol, asset_type="option", direction="long", option_type="call",
                    quantity=quantity, multiplier=100, entry_price=entry, current_price=entry + 1,
                    opened_on=DAY, expiration=DAY + timedelta(days=700), strike=300, status=status,
                ))
            session.commit()
        response = client.post("/api/market/refresh?scope=full")
        assert response.status_code == 200, response.text
        rows = {row["symbol"]: row for row in response.json()["leaps_watchlist"]}
        assert rows["QQQ"]["holding_occupancy"] == {"committed": 20000, "net_cash_flow": -1600}
        assert rows["DRAM"]["holding_occupancy"] == {"committed": 1068, "net_cash_flow": 0}
        assert rows["AAPL"]["holding_occupancy"] is None
        assert rows["SOXX"]["holding_occupancy"] is None
