from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.indicators import SupportLevel

ZERO = Decimal("0")
TRILLION_USD = Decimal("1000000000000")
LEAPS_SLOT_FRACTION = Decimal("0.20")

# The market-cap check is dynamic. This list bounds public-data requests to
# liquid US-listed names that can plausibly cross the threshold.
TRILLION_CLUB_CANDIDATES = {
    "AAPL": "Apple",
    "AMZN": "Amazon",
    "AVGO": "Broadcom",
    "BRK-B": "Berkshire Hathaway",
    "GOOG": "Alphabet Class C",
    "LLY": "Eli Lilly",
    "META": "Meta",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "TSLA": "Tesla",
    "TSM": "TSMC",
}
TRILLION_CLUB_EXCLUSIONS = frozenset(
    {"000660.KS", "MU", "ORCL", "SPACEX", "WMT"}
)
WHEEL_CLUB_EXCLUSIONS = TRILLION_CLUB_EXCLUSIONS | {"BRK-B"}


@dataclass(frozen=True)
class ClubMarketState:
    symbol: str
    close: Decimal
    previous_close: Decimal
    ma200: Decimal
    rsi14: Decimal
    current_price: Decimal | None
    change_fraction: Decimal | None
    live_quote: bool
    market_cap: Decimal | None
    market_cap_as_of: date | None
    market_cap_currency: str | None
    market_cap_live: bool
    completed_sessions: int
    two_closes_below_ma200: bool = False
    supports: tuple[SupportLevel, ...] = ()
    next_earnings_date: date | None = None
    earnings_available: bool = False


@dataclass(frozen=True)
class ClubPositionState:
    position_id: int
    symbol: str
    slot: int
    opened_on: date
    underlying_entry_price: Decimal | None
    return_fraction: Decimal | None = None


@dataclass(frozen=True)
class ClubEntryDecision:
    symbol: str
    name: str
    technical_eligible: bool
    eligible: bool
    suggested_slot: int | None
    suggested_amount: Decimal
    over_shared_budget: bool
    checks: dict[str, bool]
    current_price: Decimal | None
    previous_close: Decimal
    change_fraction: Decimal | None
    close: Decimal
    ma200: Decimal
    rsi14: Decimal
    market_cap: Decimal | None
    market_cap_as_of: date | None
    market_cap_currency: str | None
    open_slots: tuple[int, ...]
    fifo_candidate_position_id: int | None
    fifo_candidate_slot: int | None
    risk_position_ids: tuple[int, ...]


def evaluate_club_entries(
    markets: list[ClubMarketState],
    positions: list[ClubPositionState],
    shared_current: Decimal,
    shared_target: Decimal,
    *,
    qqq_above_ma200: bool,
    as_of: date,
    confirmed_entry_dates: list[date],
    slot_target: Decimal | None = None,
    symbol_commitments: dict[str, Decimal] | None = None,
    symbol_cap: Decimal | None = None,
    individual_current: Decimal | None = None,
    individual_target: Decimal | None = None,
) -> list[ClubEntryDecision]:
    pool_capacity = max(shared_target - shared_current, ZERO)
    individual_capacity = max(
        (individual_target if individual_target is not None else shared_target)
        - (individual_current if individual_current is not None else shared_current),
        ZERO,
    )
    capacity = min(pool_capacity, individual_capacity)
    weekly_limit = not any(_same_market_week(entry_date, as_of) for entry_date in confirmed_entry_dates)
    decisions: list[ClubEntryDecision] = []
    for market in markets:
        symbol_positions = sorted(
            (position for position in positions if position.symbol == market.symbol),
            key=lambda position: (position.opened_on, position.position_id),
        )
        used_slots = {position.slot for position in symbol_positions}
        open_slots = tuple(sorted(used_slots))
        available_slots = [slot for slot in range(1, 3) if slot not in used_slots]
        fifo = symbol_positions[0] if len(symbol_positions) >= 2 else None
        risk_position_ids = tuple(
            position.position_id
            for position in symbol_positions
            if market.two_closes_below_ma200
            and position.return_fraction is not None
            and position.return_fraction <= Decimal("-0.35")
        )
        checks = {
            "qqq_above_ma200": qqq_above_ma200,
            "stock_above_ma200": market.close > market.ma200,
            "rsi_below_45": market.rsi14 < Decimal("45"),
            "daily_drop": market.change_fraction is not None
            and market.change_fraction < Decimal("-0.05"),
            "live_quote": market.live_quote,
            "market_cap": market.market_cap is not None
            and market.market_cap >= TRILLION_USD
            and market.market_cap_currency == "USD"
            and market.market_cap_live,
            "history": market.completed_sessions >= 252,
            "weekly_limit": weekly_limit,
            "second_entry": _second_entry_ready(market, symbol_positions),
        }
        technical_eligible = all(checks.values())
        symbol_current = (symbol_commitments or {}).get(market.symbol, ZERO)
        symbol_capacity = (
            max(symbol_cap - symbol_current, ZERO)
            if symbol_cap is not None
            else capacity
        )
        eligible = (
            technical_eligible
            and capacity > ZERO
            and symbol_capacity > ZERO
            and bool(available_slots)
        )
        suggested_amount = (
            min(
                slot_target
                if slot_target is not None
                else shared_target * Decimal("0.10"),
                capacity,
                symbol_capacity,
            ).quantize(Decimal("0.01"))
            if eligible
            else ZERO
        )
        decisions.append(
            ClubEntryDecision(
                symbol=market.symbol,
                name=TRILLION_CLUB_CANDIDATES.get(market.symbol, market.symbol),
                technical_eligible=technical_eligible,
                eligible=eligible,
                suggested_slot=available_slots[0] if available_slots else None,
                suggested_amount=suggested_amount,
                over_shared_budget=technical_eligible
                and (pool_capacity <= ZERO or individual_capacity <= ZERO or symbol_capacity <= ZERO),
                checks=checks,
                current_price=market.current_price,
                previous_close=market.previous_close,
                change_fraction=market.change_fraction,
                close=market.close,
                ma200=market.ma200,
                rsi14=market.rsi14,
                market_cap=market.market_cap,
                market_cap_as_of=market.market_cap_as_of,
                market_cap_currency=market.market_cap_currency,
                open_slots=open_slots,
                fifo_candidate_position_id=fifo.position_id if fifo else None,
                fifo_candidate_slot=fifo.slot if fifo else None,
                risk_position_ids=risk_position_ids,
            )
        )
    return decisions


def is_club_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    return normalized in TRILLION_CLUB_CANDIDATES and normalized not in TRILLION_CLUB_EXCLUSIONS


def is_wheel_club_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    return normalized in TRILLION_CLUB_CANDIDATES and normalized not in WHEEL_CLUB_EXCLUSIONS


def _second_entry_ready(
    market: ClubMarketState,
    positions: list[ClubPositionState],
) -> bool:
    if not positions:
        return True
    return market.rsi14 < Decimal("40")


def _same_market_week(first: date, second: date) -> bool:
    return first.isocalendar()[:2] == second.isocalendar()[:2]
