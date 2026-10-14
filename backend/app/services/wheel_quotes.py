from datetime import date, datetime, time
from decimal import Decimal
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import WheelCallLot, WheelPutLot, WheelShareLot
from app.domain.option_estimator import estimate_put_range, implied_volatility_from_put
from app.domain.wheel_portfolio import early_close_signal
from app.market.base import MarketDataError, OptionDataProvider, OptionQuote, option_quote_usable, quote_metadata

ZERO = Decimal("0")


def quote_is_usable(quote: OptionQuote, as_of: date) -> bool:
    if not option_quote_usable(quote, as_of):
        return False
    middle = (quote.bid + quote.ask) / 2
    if middle <= ZERO or (quote.ask - quote.bid) / middle > Decimal("0.50"):
        return False
    return True


class WheelQuoteService:
    def __init__(self, session: Session, provider: OptionDataProvider) -> None:
        self.session = session
        self.provider = provider

    def refresh_open_lots(
        self,
        tqqq_spot: Decimal | Mapping[str, Decimal],
        as_of: date,
    ) -> None:
        spots = (
            {symbol.upper(): price for symbol, price in tqqq_spot.items()}
            if isinstance(tqqq_spot, Mapping)
            else {"TQQQ": tqqq_spot}
        )
        puts = list(
            self.session.scalars(select(WheelPutLot).where(WheelPutLot.state == "open"))
        )
        calls = list(
            self.session.scalars(select(WheelCallLot).where(WheelCallLot.state == "open"))
        )
        for record in puts:
            self._refresh_put(record, spots.get(record.symbol), as_of)
        for record in calls:
            self._refresh_call(record, as_of)
        self.session.commit()

    def _refresh_put(
        self,
        record: WheelPutLot,
        underlying_spot: Decimal | None,
        as_of: date,
    ) -> None:
        quote = self._public_quote(record.symbol, "put", record.expiration, record.strike)
        if quote is not None and quote_is_usable(quote, as_of):
            self._store_quote(record, quote)
            record.quote_source = "public"
            record.theoretical_low = None
            record.theoretical_base = None
            record.theoretical_high = None
            reference = quote.ask
        else:
            if record.quote_ask is not None and record.quote_source == "public":
                record.quote_quality = "stale"
                record.early_close_code = None
                record.early_close_message = "行情刷新失败，保留上次估值；请在券商确认当前买回价。"
                return
            if underlying_spot is None:
                self._clear_quote(record)
                record.quote_source = "unavailable"
                record.theoretical_low = None
                record.theoretical_base = None
                record.theoretical_high = None
                reference = None
            else:
                reference = self._store_theoretical(record, underlying_spot, as_of)
            if reference is not None:
                record.quote_as_of = datetime.combine(as_of, time.min)
        if reference is None:
            record.captured_fraction = None
            record.early_close_code = None
            record.early_close_message = "暂时无法估算当前期权价值。"
            return
        signal = early_close_signal(
            record.trade_date,
            record.expiration,
            as_of,
            record.premium,
            reference,
            "public" if record.quote_source == "public" and record.quote_quality in {None, "legacy", "realtime"} else "unavailable",
        )
        record.captured_fraction = signal.captured_fraction
        record.early_close_code = signal.code
        record.early_close_message = signal.message

    def _refresh_call(self, record: WheelCallLot, as_of: date) -> None:
        share = self.session.get(WheelShareLot, record.share_lot_id)
        put = self.session.get(WheelPutLot, share.put_lot_id) if share is not None else None
        quote = (
            self._public_quote(put.symbol, "call", record.expiration, record.strike)
            if put is not None
            else None
        )
        if quote is not None and quote_is_usable(quote, as_of):
            self._store_quote(record, quote)
            record.quote_source = "public"
        else:
            record.quote_quality = "stale"
            if record.quote_source != "public":
                record.quote_source = "unavailable"

    def _store_theoretical(
        self,
        record: WheelPutLot,
        tqqq_spot: Decimal,
        as_of: date,
    ) -> Decimal | None:
        opening_dte = (record.expiration - record.trade_date).days
        current_dte = max((record.expiration - as_of).days, 0)
        implied_volatility = implied_volatility_from_put(
            record.entry_tqqq_price,
            record.strike,
            opening_dte,
            record.premium,
        )
        self._clear_quote(record)
        if implied_volatility is None:
            record.quote_source = "unavailable"
            return None
        low, base, high = estimate_put_range(
            tqqq_spot,
            record.strike,
            current_dte,
            implied_volatility,
        )
        record.quote_source = "theoretical"
        record.theoretical_low = low
        record.theoretical_base = base
        record.theoretical_high = high
        return high

    def _public_quote(
        self,
        symbol: str,
        option_type: str,
        expiration: date,
        strike: Decimal,
    ) -> OptionQuote | None:
        try:
            return self.provider.option_quote(symbol, option_type, expiration, strike)
        except (MarketDataError, OSError):
            return None

    @staticmethod
    def _store_quote(record, quote: OptionQuote) -> None:
        record.quote_bid = quote.bid
        record.quote_ask = quote.ask
        record.quote_last = quote.last
        record.quote_iv = quote.implied_volatility
        record.quote_as_of = quote.fetched_at or quote.quoted_at
        for key, value in quote_metadata(quote).items():
            setattr(record, key, value)

    @staticmethod
    def _clear_quote(record) -> None:
        record.quote_bid = None
        record.quote_ask = None
        record.quote_last = None
        record.quote_iv = None
        record.quote_as_of = None
        record.quote_vendor = None
        record.quote_quality = None
        record.quote_fetched_at = None
        record.quote_market_as_of = None
