from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db_models import Base, BucketBalance
from app.market.base import MarketDataError, OptionQuote
from app.services.wheel_portfolio import WheelPortfolioService
from app.services.wheel_quotes import WheelQuoteService, quote_is_usable


class PublicQuoteProvider:
    def option_quote(self, symbol, option_type, expiration, strike):
        return OptionQuote(
            contract_symbol="TQQQ260815P00050000",
            symbol=symbol,
            option_type=option_type,
            expiration=expiration,
            strike=strike,
            bid=Decimal("0.45"),
            ask=Decimal("0.50"),
            last=Decimal("0.48"),
            implied_volatility=Decimal("0.62"),
            quoted_at=datetime(2026, 7, 8, 20, 0),
            source="yahoo",
        )


class BrokenQuoteProvider:
    def option_quote(self, symbol, option_type, expiration, strike):
        raise MarketDataError("offline")


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        value.add(BucketBalance(bucket="wheel", amount=Decimal("100000")))
        value.commit()
        yield value


def open_put(session: Session):
    return WheelPortfolioService(session).open_put(
        batch_number=1,
        trade_date=date(2026, 7, 1),
        expiration=date(2026, 8, 15),
        strike=Decimal("50"),
        premium=Decimal("1.50"),
        quantity=12,
        entry_tqqq_price=Decimal("55"),
    )


def test_public_ask_drives_actionable_early_close_signal(session: Session) -> None:
    put = open_put(session)

    WheelQuoteService(session, PublicQuoteProvider()).refresh_open_lots(
        tqqq_spot=Decimal("60"), as_of=date(2026, 7, 8)
    )

    assert put.quote_source == "public"
    assert put.quote_ask == Decimal("0.5000")
    assert put.quote_as_of == datetime(2026, 7, 8, 20, 0)
    assert put.early_close_code == "fast_profit"
    assert "建议提前平仓" in (put.early_close_message or "")
    payload = WheelPortfolioService(session).overview()["rounds"][0]["puts"][0]
    assert payload["opening_dte"] == 45
    assert payload["opening_annualized_return"] == Decimal("0.243333")
    assert payload["early_close_days"] == 7
    assert payload["early_close_annualized_return"] == Decimal("1.042858")
    assert payload["early_close_return_kind"] == "estimated"


def test_broken_public_quote_falls_back_to_theoretical_range(session: Session) -> None:
    put = open_put(session)

    WheelQuoteService(session, BrokenQuoteProvider()).refresh_open_lots(
        tqqq_spot=Decimal("65"), as_of=date(2026, 7, 8)
    )

    assert put.quote_source == "theoretical"
    assert put.theoretical_low is not None
    assert put.theoretical_base is not None
    assert put.theoretical_high is not None
    assert put.theoretical_low <= put.theoretical_base <= put.theoretical_high
    assert put.quote_as_of == datetime(2026, 7, 8)
    assert "券商确认" in (put.early_close_message or "")


def test_quote_quality_rejects_zero_bid_stale_and_wide_spread() -> None:
    base = PublicQuoteProvider().option_quote(
        "TQQQ", "put", date(2026, 8, 15), Decimal("50")
    )
    assert quote_is_usable(base, date(2026, 7, 8)) is True

    assert quote_is_usable(base.__class__(**{**base.__dict__, "bid": Decimal("0")}), date(2026, 7, 8)) is False
    assert quote_is_usable(base.__class__(**{**base.__dict__, "ask": Decimal("0.90")}), date(2026, 7, 8)) is False
    assert quote_is_usable(base.__class__(**{**base.__dict__, "quoted_at": datetime(2026, 7, 1)}), date(2026, 7, 8)) is False
