from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.core import (
    CORE_RATIO_SYMBOLS,
    CORE_ROTATION_SYMBOLS,
    CORE_SYMBOLS,
    CoreAssetInputs,
    consecutive_extreme,
    evaluate_core_portfolio,
    relative_ratio_zscores,
)
from app.domain.club_wheel import ClubWheelPositionState, evaluate_club_wheel_entries
from app.domain.indicators import (
    drawdown_from_high,
    effective_ma200_break,
    find_support_levels,
    simple_moving_average,
    wilder_rsi,
)
from app.domain.leaps import (
    ADDITIONAL_LEAPS_ETFS,
    LeapsMarketState,
    evaluate_leaps_tranches,
    select_fifo_position,
)
from app.domain.trillion_club import (
    TRILLION_CLUB_CANDIDATES,
    TRILLION_CLUB_EXCLUSIONS,
    ClubMarketState,
    ClubPositionState,
    evaluate_club_entries,
)
from app.domain.models import Bucket
from app.domain.wheel import evaluate_risk, evaluate_sell_put
from app.market.base import (
    MarketDataProvider,
    MarketDataError,
    OptionDataProvider,
    completed_daily_bars,
    is_stale,
    option_quote_usable,
    quote_metadata,
    session_quote_live,
)
from app.market.factory import market_provider
from app.market.settings import read_settings
from app.market.operations import market_operation
from app.services.portfolio_store import PortfolioStore
from app.services.signals import SignalService
from app.services.core_rotation import CoreRotationService
from app.services.wheel_cycles import WheelCycleService
from app.services.wheel_portfolio import WheelPortfolioService
from app.services.wheel_quotes import WheelQuoteService
from app.services.pmcc import pmcc_snapshot
from app.services.leaps_watchlist import PINNED_LEAPS_SYMBOLS, load_leaps_watchlist
from app.services.vix_context import load_vix_context
from app.db_models import (
    CoreTradeRecord,
    LedgerEvent,
    PositionRecord,
    UnmanagedPositionRecord,
    WheelPutLot,
    WheelRound,
    WheelShareLot,
)

router = APIRouter(prefix="/api/market", tags=["market"])
ZERO = Decimal("0")


def get_market_provider(session: Session = Depends(get_session)) -> MarketDataProvider:
    try:
        return market_provider(read_settings(session), session.get_bind())
    except MarketDataError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def get_option_provider(provider: MarketDataProvider = Depends(get_market_provider)) -> OptionDataProvider:
    return provider


def get_vix_provider(provider: MarketDataProvider = Depends(get_market_provider)) -> MarketDataProvider:
    return provider


@router.post("/refresh")
@market_operation
def refresh(
    session: Session = Depends(get_session),
    provider: MarketDataProvider = Depends(get_market_provider),
    option_provider: OptionDataProvider = Depends(get_option_provider),
    vix_provider: MarketDataProvider = Depends(get_vix_provider),
    scope: Literal["stocks", "full"] = "full",
):
    refresh_options = scope == "full"
    settings = read_settings(session)
    from app.market.ibkr import IbkrMarketDataProvider
    club_symbols = settings.club_symbols
    if isinstance(provider, IbkrMarketDataProvider):
        provider = market_provider(settings, session.get_bind())
        option_provider = provider
        vix_provider = provider
    quote_errors = []
    if hasattr(provider, "begin_refresh"):
        provider.begin_refresh()
    combined_prefetch = provider is option_provider and hasattr(provider, "prefetch_quotes")
    symbols = {*PINNED_LEAPS_SYMBOLS, "TQQQ", "VIX", *CORE_SYMBOLS, *club_symbols}
    symbols.update(session.scalars(select(UnmanagedPositionRecord.symbol).where(UnmanagedPositionRecord.status == "open", UnmanagedPositionRecord.asset_type == "equity")))
    symbols.update(session.scalars(select(PositionRecord.symbol).where(PositionRecord.status == "open", PositionRecord.asset_type == "equity")))
    contracts = []
    if refresh_options:
        from app.db_models import WheelCallLot
        for model in (PositionRecord, UnmanagedPositionRecord):
            for record in session.scalars(select(model).where(model.status == "open", model.asset_type == "option")):
                if record.option_type and record.expiration and record.strike:
                    contracts.append((record.symbol, record.option_type, record.expiration, record.strike))
        for record in session.scalars(select(WheelPutLot).where(WheelPutLot.state == "open")):
            contracts.append((record.symbol, "put", record.expiration, record.strike))
        for record in session.scalars(select(WheelCallLot).where(WheelCallLot.state == "open")):
            share = session.get(WheelShareLot, record.share_lot_id)
            put = session.get(WheelPutLot, share.put_lot_id) if share else None
            if put:
                contracts.append((put.symbol, "call", record.expiration, record.strike))
    if combined_prefetch:
        from app.services.market_prefetch import prefetch_market_data
        prefetch_market_data(
            provider, symbols, contracts,
            ("QQQ", "TQQQ", *CORE_SYMBOLS, *club_symbols, *ADDITIONAL_LEAPS_ETFS),
            (*PINNED_LEAPS_SYMBOLS, *club_symbols) if refresh_options else (),
        )
    else:
        try:
            if hasattr(provider, "prefetch_snapshots"):
                provider.prefetch_snapshots(symbols)
        except MarketDataError:
            pass  # per-symbol requests report failures, preserving good legs
        if refresh_options and hasattr(option_provider, "prefetch_options"):
            try:
                option_provider.prefetch_options(contracts)
            except MarketDataError:
                pass
    try:
        symbols_for_history = list(dict.fromkeys(("QQQ", "TQQQ", *CORE_SYMBOLS)))
        with ThreadPoolExecutor(max_workers=6) as executor:
            series = dict(zip(symbols_for_history, executor.map(lambda symbol: provider.daily_bars(symbol, 300), symbols_for_history)))
    except MarketDataError as error:
        SignalService(session).retire_market_signals()
        _refresh_equities(session, provider, {})
        failed_date = datetime.now(ZoneInfo("America/New_York")).date()
        if refresh_options:
            _refresh_unmanaged_options(session, option_provider, failed_date)
            _refresh_leaps_quotes(list(session.scalars(select(PositionRecord).where(PositionRecord.status == "open", PositionRecord.asset_type == "option"))), option_provider, failed_date)
            WheelQuoteService(session, option_provider).refresh_open_lots({}, failed_date)
        session.commit()
        raise HTTPException(status_code=503, detail=str(error)) from error

    vix_error = None
    vix = None
    try:
        vix_series = vix_provider.daily_bars("VIX", 5)
        series["VIX"] = vix_series
        if vix_series.source == "sample" or is_stale(vix_series.as_of, datetime.now(ZoneInfo("America/New_York")).date()):
            raise MarketDataError("VIX 数据已过期")
        vix = vix_series.bars[-1].close
    except (MarketDataError, OSError) as error:
        vix_error = str(error)

    qqq = series["QQQ"]
    tqqq = series["TQQQ"]
    try:
        session_quote = provider.session_quote("QQQ")
    except (AttributeError, MarketDataError, OSError):
        session_quote = None
    qqq_bars = completed_daily_bars(qqq, session_quote) if session_quote else qqq.bars
    if len(qqq_bars) < 200:
        raise HTTPException(status_code=503, detail="QQQ 完成日线不足 200 条")
    qqq_closes = [bar.close for bar in qqq_bars]
    qqq_as_of = qqq_bars[-1].date
    market_date = session_quote.market_date if session_quote else qqq_as_of
    live_session_quote = session_quote_live(session_quote)
    spots = {}
    for symbol in ("TQQQ", *CORE_SYMBOLS):
        try:
            quote = provider.session_quote(symbol)
            if quote.source != "sample" and quote.quality != "stale":
                spots[symbol] = quote.price
        except (AttributeError, MarketDataError, OSError):
            pass
    tqqq_spot = spots.get("TQQQ", tqqq.bars[-1].close)
    qqq_ma20 = simple_moving_average(qqq_closes, 20)
    qqq_ma200 = simple_moving_average(qqq_closes, 200)
    qqq_rsi = wilder_rsi(qqq_closes)
    supports = find_support_levels(tqqq.bars, tqqq_spot)
    sell_put = evaluate_sell_put(
        qqq_closes[-1],
        qqq_ma200,
        qqq_rsi,
        qqq_bars[-1].is_bearish,
        tqqq_spot,
        supports,
    )
    cycle = WheelCycleService(session).current()
    wheel_service = WheelPortfolioService(session)
    has_tqqq_exposure = cycle is not None or wheel_service.has_exposure("TQQQ")
    risk = evaluate_risk(effective_ma200_break(qqq_closes), has_tqqq_exposure)
    market_state = LeapsMarketState(
        close=qqq_closes[-1],
        previous_close=qqq_closes[-2],
        ma20=qqq_ma20,
        previous_ma20=simple_moving_average(qqq_closes[:-1], 20),
        ma200=qqq_ma200,
        drawdown=drawdown_from_high(qqq_closes),
        rsi14=qqq_rsi,
        previous_rsi14=wilder_rsi(qqq_closes[:-1]),
        previous_above_ma20=qqq_closes[-2] > simple_moving_average(qqq_closes[:-1], 20),
        two_closes_above_ma20=(
            qqq_closes[-2] > simple_moving_average(qqq_closes[:-1], 20)
            and qqq_closes[-1] > qqq_ma20
        ),
        current_price=session_quote.price if session_quote else None,
        current_change_fraction=session_quote.change_fraction if session_quote else None,
        session_quote_live=live_session_quote,
    )
    equity_quotes = _refresh_equities(session, provider, series)
    if refresh_options:
        _refresh_unmanaged_options(session, option_provider, qqq_as_of)
    portfolio = PortfolioStore(session).summary()
    total_equity = Decimal(str(portfolio.get("total_equity", ZERO)))
    pmcc_total_target = total_equity * Decimal("0.25")
    pmcc_qqq_target = total_equity * Decimal("0.10")
    pmcc_individual_target = total_equity * Decimal("0.15")
    pmcc_individual_cap = total_equity * Decimal("0.03")
    pmcc_qqq_slot_target = total_equity * Decimal("0.02")
    pmcc_individual_slot_target = total_equity * Decimal("0.015")
    target = pmcc_qqq_target
    option_target = portfolio.get("targets", {}).get("options", {}).get("amount", ZERO)
    option_capital = portfolio.get("capital", {}).get("options", {})
    option_committed = option_capital.get("committed", ZERO)
    leaps_positions = list(
        session.scalars(
            select(PositionRecord).where(
                PositionRecord.bucket == Bucket.LEAPS.value,
                PositionRecord.status == "open",
            )
        )
    )
    if refresh_options:
        _refresh_leaps_quotes(leaps_positions, option_provider, qqq_as_of)
    session.commit()
    qqq_positions = [position for position in leaps_positions if position.symbol in {"QQQ", "QLD"}]
    club_positions = [position for position in leaps_positions if position.symbol not in {"QQQ", "QLD"}]
    used_tranches = {
        position.tranche for position in qqq_positions if position.tranche is not None
    }
    qqq_committed = sum(
        (
            position.entry_price * position.quantity * position.multiplier
            for position in leaps_positions
            if position.symbol in {"QQQ", "QLD"}
        ),
        ZERO,
    )
    invested = sum(
        (
            position.current_price * position.quantity * position.multiplier
            for position in leaps_positions
        ),
        Decimal("0"),
    )
    last_leaps_entry = session.scalar(
        select(PositionRecord.opened_on)
        .where(
            PositionRecord.bucket == Bucket.LEAPS.value,
            PositionRecord.symbol.in_(["QQQ", "QLD"]),
        )
        .order_by(PositionRecord.opened_on.desc(), PositionRecord.id.desc())
        .limit(1)
    )
    leaps = evaluate_leaps_tranches(
        market_state,
        used_tranches,
        qqq_committed,
        target,
        as_of=market_date,
        last_entry_date=last_leaps_entry,
        shared_current=option_committed,
        shared_target=option_target,
    )
    base_entry_ready = bool(leaps) and all(
        value
        for key, value in leaps[0].checks.items()
        if key != "next_slot"
    )
    fifo_candidate = select_fifo_position(
        [
            (position.id, position.tranche, position.opened_on)
            for position in qqq_positions
            if position.tranche is not None
        ]
    )
    fifo = {
        "required": len(used_tranches) >= 5 and base_entry_ready,
        "candidate": fifo_candidate if len(used_tranches) >= 5 and base_entry_ready else None,
    }
    club_market_states, club_unavailable = _load_club_markets(provider, market_date,
        [symbol for symbol in club_symbols if symbol not in ADDITIONAL_LEAPS_ETFS])
    etf_market_states, etf_unavailable = _load_club_markets(provider, market_date, list(ADDITIONAL_LEAPS_ETFS))
    wheel_spots = {
        "TQQQ": tqqq_spot,
        "BRK.B": spots.get("BRK.B", series["BRK.B"].bars[-1].close),
        "VOO": spots.get("VOO", series["VOO"].bars[-1].close),
        "SCHD": spots.get("SCHD", series["SCHD"].bars[-1].close),
    }
    wheel_spots.update(
        {
            state.symbol: state.current_price or state.close
            for state in club_market_states
        }
    )
    if refresh_options:
        WheelQuoteService(session, option_provider).refresh_open_lots(wheel_spots, market_date)
    club_entry_dates = list(
        session.scalars(
            select(PositionRecord.opened_on).where(
                PositionRecord.bucket == Bucket.LEAPS.value,
                PositionRecord.symbol.not_in(["QQQ", "QLD"]),
            )
        )
    )
    club_position_states = [
        ClubPositionState(
            position_id=position.id,
            symbol=position.symbol,
            slot=position.tranche,
            opened_on=position.opened_on,
            underlying_entry_price=position.underlying_entry_price,
            return_fraction=(
                (position.current_price - position.entry_price) / position.entry_price
                if position.entry_price > 0
                else None
            ),
        )
        for position in club_positions
        if position.tranche is not None
    ]
    individual_committed = sum(
        (
            position.entry_price * position.quantity * position.multiplier
            for position in club_positions
        ),
        ZERO,
    )
    individual_decisions = evaluate_club_entries(
        [*club_market_states, *etf_market_states],
        club_position_states,
        option_committed,
        pmcc_total_target,
        qqq_above_ma200=market_state.close > market_state.ma200,
        as_of=market_date,
        confirmed_entry_dates=club_entry_dates,
        slot_target=pmcc_individual_slot_target,
        symbol_commitments={
            symbol: sum(
                (
                    position.entry_price * position.quantity * position.multiplier
                    for position in club_positions
                    if position.symbol == symbol
                ),
                ZERO,
            )
            for symbol in {*club_symbols, *ADDITIONAL_LEAPS_ETFS}
        },
        symbol_cap=pmcc_individual_cap,
        individual_current=individual_committed,
        individual_target=pmcc_individual_target,
    )
    club_decisions = [row for row in individual_decisions if row.symbol not in ADDITIONAL_LEAPS_ETFS]
    etf_decisions = [row for row in individual_decisions if row.symbol in ADDITIONAL_LEAPS_ETFS]
    club_wheel_puts = list(
        session.scalars(
            select(WheelPutLot)
            .join(WheelRound, WheelPutLot.round_id == WheelRound.id)
            .where(
                WheelPutLot.symbol != "TQQQ",
                WheelPutLot.capital_bucket == Bucket.WHEEL.value,
                WheelPutLot.state != "voided",
                WheelRound.status == "active",
            )
        )
    )
    club_wheel_put_ids = [record.id for record in club_wheel_puts]
    held_club_shares = set(
        session.scalars(
            select(WheelShareLot.put_lot_id).where(
                WheelShareLot.put_lot_id.in_(club_wheel_put_ids),
                WheelShareLot.state == "held",
                WheelShareLot.remaining_quantity > 0,
            )
        )
    ) if club_wheel_put_ids else set()
    club_wheel_positions = [
        ClubWheelPositionState(
            put_id=record.id,
            symbol=record.symbol,
            strike=record.strike,
            state=record.state,
            captured_fraction=record.captured_fraction,
            has_held_shares=record.id in held_club_shares,
        )
        for record in club_wheel_puts
    ]
    club_wheel_entry_dates = list(
        session.scalars(
            select(WheelPutLot.trade_date).where(
                WheelPutLot.symbol != "TQQQ",
                WheelPutLot.capital_bucket == Bucket.WHEEL.value,
                WheelPutLot.state != "voided",
            )
        )
    )
    wheel_overview = wheel_service.overview()
    underlying_prices = {
        "QQQ": session_quote.price if session_quote else qqq_closes[-1],
        **{
            state.symbol: state.current_price or state.close
            for state in club_market_states
        },
        **{
            position.symbol: position.current_price
            for position in leaps_positions
            if position.symbol == "QLD"
        },
    }
    for symbol in ADDITIONAL_LEAPS_ETFS:
        try:
            underlying_prices[symbol] = provider.session_quote(symbol).price
        except (AttributeError, MarketDataError, OSError):
            pass
    pmcc = pmcc_snapshot(
        session,
        as_of=market_date,
        underlying_prices=underlying_prices,
    )
    pmcc_states = pmcc.get("states", [])
    qqq_available_contracts = sum(
        (
            max(
                Decimal(str(state["covered_contracts"]))
                - Decimal(str(state["short_quantity"])),
                ZERO,
            )
            for state in pmcc_states
            if state["symbol"] in {"QQQ", "QLD"}
            and state["long_position_id"] is not None
        ),
        ZERO,
    )
    individual_available_symbols = [
        state["symbol"]
        for state in pmcc_states
        if state["symbol"] not in {"QQQ", "QLD"}
        and state["long_position_id"] is not None
        and Decimal(str(state["covered_contracts"]))
        > Decimal(str(state["short_quantity"]))
    ]
    individual_available_set = set(individual_available_symbols)
    pmcc["entry"] = {
        "qqq": {
            "eligible": bool(base_entry_ready and qqq_available_contracts > ZERO),
            "checks": leaps[0].checks if leaps else {},
            "available_contracts": qqq_available_contracts,
            "message": (
                "复用 QQQ LEAPS 条件，已有 Long LEAPS 可覆盖 Short Call"
                if qqq_available_contracts > ZERO
                else "需先持有有效的 QQQ/QLD Long LEAPS"
            ),
        },
        "individual": {
            "eligible_symbols": [
                decision.symbol
                for decision in individual_decisions
                if decision.technical_eligible
                and decision.symbol in individual_available_set
            ],
            "checks_reused": True,
            "message": "复用万亿俱乐部 LEAPS 条件，且必须已有可覆盖的 Long LEAPS",
        },
    }
    club_wheel_decisions = evaluate_club_wheel_entries(
        club_market_states,
        club_wheel_positions,
        qqq_above_ma200=market_state.close > market_state.ma200,
        total_equity=portfolio.get("total_equity", ZERO),
        wheel_budget_available=wheel_overview["budget"]["available"],
        as_of=market_date,
        confirmed_entry_dates=club_wheel_entry_dates,
    )
    core_positions = list(
        session.scalars(
            select(PositionRecord).where(
                PositionRecord.bucket == Bucket.CORE.value,
                PositionRecord.asset_type == "equity",
                PositionRecord.status == "open",
            )
        )
    )
    core_target = portfolio.get("targets", {}).get("core", {}).get("amount", Decimal("0"))
    core_capital = portfolio.get("capital", {}).get("core", {})
    cash_capital = portfolio.get("capital", {}).get("cash", {})
    core_available = Decimal(str(core_capital.get("available", 0)))
    cash_available = Decimal(str(cash_capital.get("available", 0)))
    pending_core_collateral = sum(
        (Decimal(str(put["collateral"])) for put in wheel_overview["core_puts"]),
        ZERO,
    )
    core_events = list(
        session.scalars(
            select(LedgerEvent)
            .where(
                LedgerEvent.event_type == "position_open",
                LedgerEvent.bucket == Bucket.CORE.value,
            )
            .order_by(LedgerEvent.occurred_on.desc(), LedgerEvent.id.desc())
        )
    )
    last_core_put_date = session.scalar(
        select(WheelPutLot.trade_date)
        .where(WheelPutLot.capital_bucket == Bucket.CORE.value, WheelPutLot.state != "voided")
        .order_by(WheelPutLot.trade_date.desc())
        .limit(1)
    )
    last_core_entry_date = max(
        (value for value in (core_events[0].occurred_on if core_events else None, last_core_put_date) if value),
        default=None,
    )
    last_core_trade = session.scalar(select(CoreTradeRecord.traded_at).order_by(CoreTradeRecord.traded_at.desc()).limit(1))
    if last_core_trade:
        last_core_entry_date = max(last_core_entry_date or last_core_trade.date(), last_core_trade.date())
    brk_by_date = {bar.date: bar.close for bar in series["BRK.B"].bars}
    voo_by_date = {bar.date: bar.close for bar in series["VOO"].bars}
    common_dates = sorted(set(brk_by_date) & set(voo_by_date))
    brk_aligned = [brk_by_date[value] for value in common_dates]
    voo_aligned = [voo_by_date[value] for value in common_dates]
    ratio_zscores = relative_ratio_zscores(brk_aligned, voo_aligned)
    ratio_z = ratio_zscores[-1] if ratio_zscores else ZERO
    completed_core = {}
    for symbol in CORE_SYMBOLS:
        bars = completed_daily_bars(series[symbol], session_quote) if session_quote else [
            bar for bar in series[symbol].bars if bar.date < datetime.now(ZoneInfo("America/New_York")).date()
        ]
        completed_core[symbol] = {bar.date: bar.close for bar in bars}
    rotation_dates = sorted(
        set.intersection(*(set(completed_core[symbol]) for symbol in CORE_SYMBOLS))
    )
    rotation_ratios = [(day, completed_core["BRK.B"][day] / completed_core["VOO"][day])
                       for day in rotation_dates if min(completed_core[symbol][day] for symbol in CORE_RATIO_SYMBOLS) > ZERO]
    rotation_valid = bool(rotation_dates) and all(
        series[symbol].source != "sample"
        and not is_stale(rotation_dates[-1], date.today())
        and sorted(completed_core[symbol])[-21:] == rotation_dates[-21:]
        for symbol in CORE_SYMBOLS
    ) and len(rotation_ratios) == len(rotation_dates)
    rotation_usage, rotation_executions = CoreRotationService(session).usage(completed_core)
    core_assets = []
    for symbol in CORE_SYMBOLS:
        symbol_series = series[symbol]
        bars = completed_daily_bars(symbol_series, session_quote) if session_quote else symbol_series.bars
        closes = [bar.close for bar in bars]
        symbol_price = spots.get(symbol, closes[-1])
        latest_symbol_event = next(
            (event for event in core_events if event.details.get("symbol") == symbol),
            None,
        )
        ma200 = simple_moving_average(closes, 200)
        previous_ma200 = simple_moving_average(closes[:-1], 200)
        core_supports = find_support_levels(bars, symbol_price)
        core_assets.append(
            CoreAssetInputs(
                symbol=symbol,
                support_price=core_supports[0].price if core_supports else None,
                current_value=sum(
                    (
                        position.quantity * position.multiplier * symbol_price
                        for position in core_positions
                        if position.symbol == symbol
                    ),
                    ZERO,
                ),
                price=symbol_price,
                drawdown=drawdown_from_high(closes),
                daily_change=(closes[-1] / closes[-2] - Decimal("1")),
                rsi14=wilder_rsi(closes),
                ma200=ma200,
                below_ma200_two_days=(
                    closes[-1] < ma200 and closes[-2] < previous_ma200
                ),
                return_20d=(closes[-1] / closes[-21] - Decimal("1")),
                return_126d=(closes[-1] / closes[-127] - Decimal("1")),
                last_purchase_date=(
                    latest_symbol_event.occurred_on if latest_symbol_event else None
                ),
                last_purchase_tier=(
                    latest_symbol_event.details.get("core_signal_code", "monthly")
                    if latest_symbol_event
                    else None
                ),
            )
        )
    core_decision = evaluate_core_portfolio(
        core_assets,
        as_of=max(series[symbol].as_of for symbol in CORE_SYMBOLS),
        total_target=core_target,
        total_equity=Decimal(str(portfolio.get("total_equity", 0))),
        available_funding=core_available + cash_available,
        vix=vix,
        ratio_z=ratio_z,
        route_confirmation_days=consecutive_extreme(ratio_zscores, Decimal("1")),
        rotation_confirmation_days=0,
        last_account_purchase_date=last_core_entry_date,
        last_rotation_date=None,
        ratio_reset_since_rotation=True,
        pending_put_collateral=pending_core_collateral,
        rotation_ratios=rotation_ratios,
        rotation_usage=rotation_usage,
        pending_brk_shares=sum((Decimal(str(put["open_quantity"])) * 100 for put in wheel_overview["core_puts"] if put["symbol"] == "BRK.B"), ZERO),
        pending_voo_shares=sum((Decimal(str(put["open_quantity"])) * 100 for put in wheel_overview["core_puts"] if put["symbol"] == "VOO"), ZERO),
        pending_schd_shares=sum((Decimal(str(put["open_quantity"])) * 100 for put in wheel_overview["core_puts"] if put["symbol"] == "SCHD"), ZERO),
        rotation_data_valid=rotation_valid,
        rotation_prices={symbol: completed_core[symbol][rotation_dates[-1]] for symbol in CORE_SYMBOLS} if rotation_dates else {},
    )
    core_payload = asdict(core_decision)
    core_payload["rotation"]["executions"] = rotation_executions
    core_payload["core_available"] = core_available
    core_payload["cash_available"] = cash_available
    if core_payload["recommendation"] is not None:
        executable = Decimal(str(core_payload["recommendation"]["executable_amount"]))
        core_payload["recommendation"]["cash_required"] = max(
            executable - core_available,
            ZERO,
        )
    stale = is_stale(qqq_as_of, date.today())
    signal_service = SignalService(session)
    signal_service.retire_wheel_signals()
    if vix is None:
        signal_service.retire_market_signals(prefixes=("vix_high", "core_buy_"))
    if risk.severity == "critical":
        signal_service.emit("ma200_break", "跌破牛熊分界线", risk.message, "critical", market_date, stale=stale)
    if vix is not None and vix >= Decimal("30"):
        signal_service.emit(
            "vix_high", "VIX 达到 30", "评估是否动用现金储备。", "warning", market_date, stale=stale
        )
    core_market_date = max(series[symbol].as_of for symbol in CORE_SYMBOLS)
    signal_service.sync_core_buy(
        core_decision.recommendation,
        core_market_date,
        put=core_decision.sell_put,
        stale=vix is None or any(
            series[symbol].source == "sample" or is_stale(series[symbol].as_of, date.today())
            for symbol in CORE_SYMBOLS
        ),
    )
    signal_service.sync_core_rotation(core_decision.rotation, core_market_date, stale=not rotation_valid)
    if any(decision.eligible for decision in leaps) or fifo["required"]:
        signal_service.emit(
            "leaps_entry_opportunity",
            "QQQ LEAPS 开仓机会",
            "QQQ 趋势、RSI 与单日跌幅条件同时满足。",
            "opportunity",
            market_date,
            stale=stale or not live_session_quote,
        )
    club_opportunities = [decision for decision in club_decisions if decision.technical_eligible]
    if club_opportunities:
        strongest = min(
            club_opportunities,
            key=lambda decision: (decision.change_fraction or Decimal("0"), decision.symbol),
        )
        signal_service.emit(
            f"trillion_club_{strongest.symbol.lower().replace('.', '_').replace('-', '_')}",
            f"{strongest.symbol} 万亿俱乐部 LEAPS 机会",
            "观察列表内个股趋势、RSI 与单日跌幅条件同时满足；成交仍由用户确认。",
            "opportunity",
            market_date,
            stale=stale,
        )
    for decision in etf_decisions:
        if decision.technical_eligible:
            signal_service.emit(f"leaps_etf_{decision.symbol.lower()}", f"{decision.symbol} ETF LEAPS 机会",
                "趋势、RSI 与单日跌幅条件满足万亿俱乐部同一套 LEAPS 规则；成交仍由用户确认。",
                "opportunity", market_date, stale=stale)
    leaps_watchlist = load_leaps_watchlist(provider, club_symbols, series, refresh_iv=refresh_options)
    if refresh_options:
        occupancy_by_symbol = {}
        for state in pmcc_states:
            if state["long_position_id"] is None:
                continue
            occupancy = occupancy_by_symbol.setdefault(state["symbol"], {"committed": ZERO, "net_cash_flow": ZERO})
            occupancy["committed"] += state["long_debit"]
            occupancy["net_cash_flow"] += state["net_cash_flow"]
        for row in leaps_watchlist:
            row["holding_occupancy"] = occupancy_by_symbol.get(row["symbol"])
    sources = {value.source for value in series.values()}
    if session_quote is not None:
        sources.add(session_quote.source)
    if hasattr(provider, "warnings"):
        quote_errors.extend(provider.warnings())
    reconciliation = None
    if isinstance(provider, IbkrMarketDataProvider):
        from app.services.broker_reconciliation import reconcile_positions
        try:
            reconciliation = reconcile_positions(session, provider.connection)
            if reconciliation["differences"]:
                quote_errors.append({"symbol": "持仓核对", "error": f"盈透当前持仓与本地账本有 {len(reconciliation['differences'])} 项数量差异，请导入最新活动报表更新交易记录。"})
        except MarketDataError as error:
            quote_errors.append({"symbol": "持仓核对", "error": str(error)})
    return {
        "refresh_scope": scope,
        "source": sources.pop() if len(sources) == 1 else "mixed",
        "as_of": market_date,
        "stale": stale,
        "primary_provider": settings.effective_provider,
        "config_key": settings.config_key,
        "vix_provider": series["VIX"].source if "VIX" in series else settings.effective_provider,
        "broker_positions": reconciliation,
        "leaps_watchlist": leaps_watchlist,
        "vix_context": load_vix_context(vix_provider),
        "errors": quote_errors + ([{"symbol": "VIX", "error": vix_error}] if vix_error else []),
        "market": {
            "qqq": {
                "price": qqq_closes[-1],
                "ma20": qqq_ma20,
                "ma200": qqq_ma200,
                "rsi14": qqq_rsi,
                "bearish": qqq_bars[-1].is_bearish,
                "drawdown": market_state.drawdown,
            },
            "tqqq": {"price": tqqq_spot},
            "brk_b": {"price": series["BRK.B"].bars[-1].close},
            "voo": {"price": series["VOO"].bars[-1].close},
            "schd": {"price": series["SCHD"].bars[-1].close},
            "vix": {"price": vix, "source": series["VIX"].source if "VIX" in series else settings.effective_provider, "as_of": series["VIX"].as_of if "VIX" in series else None, "error": vix_error},
        },
        "wheel": {
            "eligible": sell_put.eligible,
            "checks": sell_put.checks,
            "dte_range": [sell_put.dte_min, sell_put.dte_max],
            "delta_range": [sell_put.delta_min, sell_put.delta_max],
            "reference_strike": sell_put.reference_strike,
            "preferred_support": sell_put.preferred_support,
            "supports": supports[:4],
        },
        "wheel_club": {
            "decisions": club_wheel_decisions,
            "unavailable": club_unavailable,
            "weekly_limit_days": 7,
            "single_stock_fraction": Decimal("0.05"),
        },
        "risk": risk,
        "leaps": leaps,
        "leaps_fifo": fifo,
        "leaps_technical_ready": base_entry_ready,
        "leaps_shared_budget": {
            "target": pmcc_total_target,
            "current": option_committed,
            "available": max(pmcc_total_target - option_committed, ZERO),
            "over": max(option_committed - pmcc_total_target, ZERO),
        },
        "pmcc": pmcc,
        "leaps_club": {
            "decisions": club_decisions,
            "unavailable": club_unavailable,
            "exclusions": sorted(TRILLION_CLUB_EXCLUSIONS),
        },
        "leaps_etfs": {"decisions": etf_decisions, "unavailable": etf_unavailable},
        "leaps_session": {
            "available": live_session_quote,
            "price": session_quote.price if session_quote else None,
            "previous_close": session_quote.previous_close if session_quote else qqq_closes[-1],
            "change_fraction": session_quote.change_fraction if session_quote else None,
            "quoted_at": session_quote.quoted_at if session_quote else None,
            "market_date": market_date,
            "session": session_quote.session if session_quote else "unavailable",
            "source": session_quote.source if session_quote else None,
            "quality": session_quote.quality if session_quote else "unavailable",
            "fetched_at": session_quote.fetched_at if session_quote else None,
            "market_as_of": session_quote.market_as_of if session_quote else None,
        },
        "equities": equity_quotes,
        "core": core_payload,
    }


def _load_club_markets(
    provider: MarketDataProvider,
    market_date: date,
    symbols: list[str],
) -> tuple[list[ClubMarketState], list[dict]]:
    states: list[ClubMarketState] = []
    unavailable: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_load_club_market, provider, symbol, market_date): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                states.append(future.result())
            except (AttributeError, MarketDataError, OSError, KeyError, ValueError) as error:
                unavailable.append(
                    {
                        "symbol": symbol,
                        "name": TRILLION_CLUB_CANDIDATES.get(symbol, symbol),
                        "error": str(error),
                    }
                )
    states.sort(key=lambda state: state.symbol)
    unavailable.sort(key=lambda item: item["symbol"])
    return states, unavailable


def _load_club_market(
    provider: MarketDataProvider,
    symbol: str,
    market_date: date,
) -> ClubMarketState:
    is_etf = symbol in ADDITIONAL_LEAPS_ETFS
    loader = getattr(provider, "watchlist_bars", provider.daily_bars) if is_etf else provider.daily_bars
    series = loader(symbol, 300)
    quote = provider.session_quote(symbol)
    bars = completed_daily_bars(series, quote)
    if len(bars) < 2 or (len(bars) < 200 and not is_etf):
        raise MarketDataError(f"{symbol} 完成日线不足 200 条")
    closes = [bar.close for bar in bars]
    return ClubMarketState(
        symbol=symbol,
        close=closes[-1],
        previous_close=closes[-2],
        ma200=simple_moving_average(closes, 200) if len(closes) >= 200 else None,
        rsi14=wilder_rsi(closes) if len(closes) >= 15 else None,
        current_price=quote.price,
        change_fraction=quote.change_fraction,
        live_quote=series.source != "sample" and session_quote_live(quote),
        market_cap=None,
        market_cap_as_of=None,
        market_cap_currency=None,
        market_cap_live=False,
        club_member=True,
        completed_sessions=len(bars),
        two_closes_below_ma200=(
            len(closes) >= 201
            and closes[-1] < simple_moving_average(closes, 200)
            and closes[-2] < simple_moving_average(closes[:-1], 200)
        ),
        supports=tuple(find_support_levels(bars, quote.price)[:4]),
    )


def _refresh_equities(
    session: Session,
    provider: MarketDataProvider,
    fixed_series: dict[str, object],
) -> dict[str, dict]:
    other_records = list(
        session.scalars(
            select(UnmanagedPositionRecord).where(
                UnmanagedPositionRecord.asset_type == "equity",
                UnmanagedPositionRecord.status == "open",
            )
        )
    )
    equity_positions = list(
        session.scalars(
            select(PositionRecord).where(
                PositionRecord.asset_type == "equity",
                PositionRecord.status == "open",
            )
        )
    )
    symbols = {record.symbol for record in other_records}
    symbols.update(position.symbol for position in equity_positions)
    results: dict[str, dict] = {}
    for symbol in sorted(symbols):
        try:
            try:
                quote = provider.session_quote(symbol)
                price, source = quote.price, quote.source
                timestamp = quote.market_as_of or quote.fetched_at or quote.quoted_at
                day = timestamp.astimezone(ZoneInfo("America/New_York")).date() if timestamp.tzinfo else timestamp.date()
                metadata = quote_metadata(quote)
                if quote.quality == "stale":
                    raise MarketDataError("最新股票报价已过期")
            except AttributeError:
                # Compatibility for providers that supply only daily history.
                value = fixed_series.get(symbol) or provider.daily_bars(symbol, 5)
                price, source, day = value.bars[-1].close, value.source, value.as_of
                timestamp = datetime.combine(day, datetime.min.time())
                metadata = {}
            if source == "sample":
                raise MarketDataError("公开行情不可用，未使用模拟价格估值")
            if price <= ZERO:
                raise MarketDataError("股票价格无效")
            for record in other_records:
                if record.symbol == symbol:
                    record.current_price = price
                    record.quote_source = source
                    record.quote_as_of = day
                    record.last_error = None
                    for key, item in metadata.items():
                        setattr(record, key, item)
            for position in equity_positions:
                if position.symbol == symbol:
                    position.current_price = price
                    position.quote_source = source
                    position.quote_as_of = timestamp
                    position.last_error = None
                    for key, item in metadata.items():
                        setattr(position, key, item)
            results[symbol] = {
                "price": price,
                "source": source,
                "as_of": day,
                **metadata,
                "status": "updated",
                "error": None,
            }
        except (MarketDataError, OSError, KeyError) as error:
            matching_record = next(
                (record for record in other_records if record.symbol == symbol), None
            )
            matching_position = next(
                (position for position in equity_positions if position.symbol == symbol),
                None,
            )
            matching = matching_record or matching_position
            for record in [*other_records, *equity_positions]:
                if record.symbol == symbol:
                    record.last_error = str(error)
                    record.quote_quality = "stale"
            results[symbol] = {
                "price": matching.current_price if matching is not None else None,
                "source": matching.quote_source if matching is not None else None,
                "as_of": matching.quote_as_of if matching is not None else None,
                "status": "stale" if matching is not None and matching.current_price is not None else "unavailable",
                "error": str(error),
            }
    session.commit()
    return results


def _refresh_unmanaged_options(
    session: Session,
    provider: OptionDataProvider,
    as_of: date,
) -> None:
    records = list(
        session.scalars(
            select(UnmanagedPositionRecord).where(
                UnmanagedPositionRecord.asset_type == "option",
                UnmanagedPositionRecord.status == "open",
            )
        )
    )
    for record in records:
        if not all((record.option_type, record.expiration, record.strike)):
            continue
        try:
            quote = provider.option_quote(
                record.symbol,
                record.option_type,
                record.expiration,
                record.strike,
            )
            if not option_quote_usable(quote, as_of):
                raise MarketDataError("其他期权报价不可用")
            record.current_price = quote.bid if record.direction == "long" else quote.ask
            record.quote_source = quote.source
            record.quote_as_of = (quote.fetched_at or quote.quoted_at).date()
            for key, item in quote_metadata(quote).items():
                setattr(record, key, item)
            record.last_error = None
        except (MarketDataError, OSError) as error:
            record.last_error = str(error)
            record.quote_quality = "stale"
    session.commit()


def _refresh_leaps_quotes(
    positions: list[PositionRecord],
    provider: OptionDataProvider,
    as_of: date,
) -> None:
    for position in positions:
        if position.expiration is None or position.strike is None:
            continue
        try:
            quote = provider.option_quote(
                position.symbol, "call", position.expiration, position.strike
            )
            if not option_quote_usable(quote, as_of):
                raise MarketDataError("LEAPS 期权报价不可用")
            position.quote_source = quote.source
            position.quote_bid = quote.bid
            position.quote_ask = quote.ask
            position.quote_last = quote.last
            position.quote_iv = quote.implied_volatility
            position.quote_as_of = quote.fetched_at or quote.quoted_at
            position.last_error = None
            for key, item in quote_metadata(quote).items():
                setattr(position, key, item)
            position.peak_bid = max(position.peak_bid or quote.bid, quote.bid)
            position.current_price = quote.bid
        except (MarketDataError, OSError) as error:
            position.last_error = str(error)
            position.quote_quality = "stale"
