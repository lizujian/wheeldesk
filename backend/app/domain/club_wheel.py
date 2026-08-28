from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR

from app.domain.indicators import SupportLevel
from app.domain.trillion_club import (
    ClubMarketState,
    TRILLION_CLUB_CANDIDATES,
    is_wheel_club_symbol,
)

ZERO = Decimal("0")
SINGLE_STOCK_FRACTION = Decimal("0.05")
DAILY_DROP_TRIGGER = Decimal("-0.03")
MIN_OPENING_ANNUALIZED = Decimal("0.12")


@dataclass(frozen=True)
class ClubWheelPositionState:
    put_id: int
    symbol: str
    strike: Decimal
    state: str
    captured_fraction: Decimal | None
    has_held_shares: bool


@dataclass(frozen=True)
class ClubWheelDecision:
    symbol: str
    name: str
    technical_eligible: bool
    eligible: bool
    checks: dict[str, bool]
    current_price: Decimal | None
    previous_close: Decimal
    change_fraction: Decimal | None
    close: Decimal
    ma200: Decimal
    rsi14: Decimal
    preferred_support: SupportLevel | None
    supports: tuple[SupportLevel, ...]
    reference_strike: Decimal | None
    dte_range: tuple[int, int]
    delta_range: tuple[Decimal, Decimal]
    minimum_annualized_return: Decimal
    one_contract_collateral: Decimal | None
    concentration_limit: Decimal
    budget_available: Decimal
    over_concentration: bool
    over_budget: bool
    active_cycle: bool
    next_earnings_date: date | None
    earnings_available: bool
    earnings_confirmation_required: bool
    high_risk_put_ids: tuple[int, ...]


def evaluate_club_wheel_entries(
    markets: list[ClubMarketState],
    positions: list[ClubWheelPositionState],
    *,
    qqq_above_ma200: bool,
    total_equity: Decimal,
    wheel_budget_available: Decimal,
    as_of: date,
    confirmed_entry_dates: list[date],
) -> list[ClubWheelDecision]:
    concentration_limit = (total_equity * SINGLE_STOCK_FRACTION).quantize(Decimal("0.01"))
    weekly_limit = not any(_same_market_week(entry_date, as_of) for entry_date in confirmed_entry_dates)
    decisions: list[ClubWheelDecision] = []
    for market in markets:
        if not is_wheel_club_symbol(market.symbol):
            continue
        symbol_positions = [position for position in positions if position.symbol == market.symbol]
        active_cycle = bool(symbol_positions)
        confirmed_supports = tuple(level for level in market.supports if level.touches >= 2)
        preferred_support = confirmed_supports[0] if confirmed_supports else None
        reference_strike = _reference_strike(market.current_price, preferred_support)
        one_contract_collateral = (
            reference_strike * Decimal("100") if reference_strike is not None else None
        )
        over_concentration = (
            one_contract_collateral is not None
            and one_contract_collateral > concentration_limit
        )
        over_budget = (
            one_contract_collateral is not None
            and one_contract_collateral > wheel_budget_available
        )
        earnings_clear = (
            market.next_earnings_date is None
            or market.next_earnings_date > as_of + timedelta(days=45)
        )
        checks = {
            "qqq_above_ma200": qqq_above_ma200,
            "stock_above_ma200": market.close > market.ma200,
            "rsi_below_40": market.rsi14 < Decimal("40"),
            "daily_drop": market.change_fraction is not None
            and market.change_fraction <= DAILY_DROP_TRIGGER,
            "confirmed_support": preferred_support is not None,
            "earnings_clear": earnings_clear,
            "live_quote": market.live_quote,
            "market_cap": market.market_cap_live,
            "history": market.completed_sessions >= 252,
            "weekly_limit": weekly_limit,
            "no_active_cycle": not active_cycle,
        }
        technical_eligible = all(checks.values())
        high_risk_put_ids = tuple(
            position.put_id
            for position in symbol_positions
            if market.two_closes_below_ma200
            and (
                position.has_held_shares
                or (market.current_price is not None and market.current_price <= position.strike)
                or (
                    position.captured_fraction is not None
                    and position.captured_fraction <= Decimal("-1")
                )
            )
        )
        decisions.append(
            ClubWheelDecision(
                symbol=market.symbol,
                name=TRILLION_CLUB_CANDIDATES.get(market.symbol, market.symbol),
                technical_eligible=technical_eligible,
                eligible=technical_eligible and not over_concentration and not over_budget,
                checks=checks,
                current_price=market.current_price,
                previous_close=market.previous_close,
                change_fraction=market.change_fraction,
                close=market.close,
                ma200=market.ma200,
                rsi14=market.rsi14,
                preferred_support=preferred_support,
                supports=confirmed_supports,
                reference_strike=reference_strike,
                dte_range=(30, 45),
                delta_range=(Decimal("0.15"), Decimal("0.25")),
                minimum_annualized_return=MIN_OPENING_ANNUALIZED,
                one_contract_collateral=one_contract_collateral,
                concentration_limit=concentration_limit,
                budget_available=wheel_budget_available,
                over_concentration=over_concentration,
                over_budget=over_budget,
                active_cycle=active_cycle,
                next_earnings_date=market.next_earnings_date,
                earnings_available=market.earnings_available,
                earnings_confirmation_required=True,
                high_risk_put_ids=high_risk_put_ids,
            )
        )
    return decisions


def _reference_strike(
    current_price: Decimal | None,
    preferred_support: SupportLevel | None,
) -> Decimal | None:
    if current_price is None or current_price <= ZERO or preferred_support is None:
        return None
    conservative = min(current_price * Decimal("0.90"), preferred_support.price)
    return conservative.quantize(Decimal("1"), rounding=ROUND_FLOOR)


def _same_market_week(first: date, second: date) -> bool:
    return first.isocalendar()[:2] == second.isocalendar()[:2]
