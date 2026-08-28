from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.core import (
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
    LeapsMarketState,
    evaluate_leaps_tranches,
    select_fifo_position,
)
from app.domain.trillion_club import (
    TRILLION_CLUB_CANDIDATES,
    TRILLION_CLUB_EXCLUSIONS,
    ClubMarketState,
    ClubPositionState,
    TRILLION_USD,
    evaluate_club_entries,
    is_club_symbol,
)
from app.domain.models import Bucket
from app.domain.wheel import evaluate_risk, evaluate_sell_put
from app.market.base import (
    FallbackMarketDataProvider,
    MarketDataProvider,
    MarketDataError,
    OptionDataProvider,
    completed_daily_bars,
    is_stale,
)
from app.market.sample import SampleMarketDataProvider
from app.market.yahoo import YahooMarketDataProvider
from app.services.portfolio_store import PortfolioStore
from app.services.signals import SignalService
from app.services.wheel_cycles import WheelCycleService
from app.services.wheel_portfolio import WheelPortfolioService
from app.services.wheel_quotes import WheelQuoteService
from app.db_models import (
    LedgerEvent,
    PositionRecord,
    UnmanagedPositionRecord,
    WheelPutLot,
    WheelRound,
    WheelShareLot,
)

router = APIRouter(prefix="/api/market", tags=["market"])
ZERO = Decimal("0")


def get_market_provider() -> MarketDataProvider:
    return FallbackMarketDataProvider(YahooMarketDataProvider(), SampleMarketDataProvider())


def get_option_provider() -> OptionDataProvider:
    return YahooMarketDataProvider()


@router.post("/refresh")
def refresh(
    session: Session = Depends(get_session),
    provider: MarketDataProvider = Depends(get_market_provider),
    option_provider: OptionDataProvider = Depends(get_option_provider),
):
    try:
        series = {
            symbol: provider.daily_bars(symbol, 300)
            for symbol in ("QQQ", "TQQQ", "BRK.B", "VOO", "VIX")
        }
    except MarketDataError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

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
    live_session_quote = session_quote is not None and session_quote.source != "sample"
    tqqq_spot = tqqq.bars[-1].close
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
    _refresh_unmanaged_options(session, option_provider, qqq_as_of)
    portfolio = PortfolioStore(session).summary()
    target = portfolio.get("targets", {}).get("leaps", {}).get("amount", ZERO)
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
    _refresh_leaps_quotes(leaps_positions, option_provider, qqq_as_of)
    session.commit()
    qqq_positions = [position for position in leaps_positions if not is_club_symbol(position.symbol)]
    club_positions = [position for position in leaps_positions if is_club_symbol(position.symbol)]
    used_tranches = {
        position.tranche for position in qqq_positions if position.tranche is not None
    }
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
        invested,
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
    club_market_states, club_unavailable = _load_club_markets(provider, market_date)
    wheel_spots = {"TQQQ": tqqq_spot}
    wheel_spots.update(
        {
            state.symbol: state.current_price or state.close
            for state in club_market_states
        }
    )
    WheelQuoteService(session, option_provider).refresh_open_lots(wheel_spots, market_date)
    club_entry_dates = list(
        session.scalars(
            select(PositionRecord.opened_on).where(
                PositionRecord.bucket == Bucket.LEAPS.value,
                PositionRecord.symbol.in_(list(TRILLION_CLUB_CANDIDATES)),
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
    club_decisions = evaluate_club_entries(
        club_market_states,
        club_position_states,
        option_committed,
        option_target,
        qqq_above_ma200=market_state.close > market_state.ma200,
        as_of=market_date,
        confirmed_entry_dates=club_entry_dates,
        slot_target=target * Decimal("0.20"),
    )
    club_wheel_puts = list(
        session.scalars(
            select(WheelPutLot)
            .join(WheelRound, WheelPutLot.round_id == WheelRound.id)
            .where(
                WheelPutLot.symbol != "TQQQ",
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
                WheelPutLot.state != "voided",
            )
        )
    )
    wheel_overview = wheel_service.overview()
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
    last_rotation_event = session.scalar(
        select(LedgerEvent)
        .where(LedgerEvent.event_type.in_(("core_rotation_leg", "core_rebalance_sale")))
        .order_by(LedgerEvent.occurred_on.desc(), LedgerEvent.id.desc())
        .limit(1)
    )
    brk_by_date = {bar.date: bar.close for bar in series["BRK.B"].bars}
    voo_by_date = {bar.date: bar.close for bar in series["VOO"].bars}
    common_dates = sorted(set(brk_by_date) & set(voo_by_date))
    brk_aligned = [brk_by_date[value] for value in common_dates]
    voo_aligned = [voo_by_date[value] for value in common_dates]
    ratio_zscores = relative_ratio_zscores(brk_aligned, voo_aligned)
    ratio_z = ratio_zscores[-1] if ratio_zscores else ZERO
    ratio_dates = common_dates[251:] if len(common_dates) >= 252 else []
    ratio_reset = last_rotation_event is None or any(
        value_date > last_rotation_event.occurred_on and abs(value) <= Decimal("1")
        for value_date, value in zip(ratio_dates, ratio_zscores, strict=True)
    )
    core_assets = []
    for symbol in CORE_SYMBOLS:
        symbol_series = series[symbol]
        closes = [bar.close for bar in symbol_series.bars]
        symbol_price = closes[-1]
        latest_symbol_event = next(
            (event for event in core_events if event.details.get("symbol") == symbol),
            None,
        )
        ma200 = simple_moving_average(closes, 200)
        previous_ma200 = simple_moving_average(closes[:-1], 200)
        core_assets.append(
            CoreAssetInputs(
                symbol=symbol,
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
        vix=series["VIX"].bars[-1].close,
        ratio_z=ratio_z,
        route_confirmation_days=consecutive_extreme(ratio_zscores, Decimal("1")),
        rotation_confirmation_days=consecutive_extreme(ratio_zscores, Decimal("2")),
        last_account_purchase_date=(core_events[0].occurred_on if core_events else None),
        last_rotation_date=(last_rotation_event.occurred_on if last_rotation_event else None),
        ratio_reset_since_rotation=ratio_reset,
    )
    core_payload = asdict(core_decision)
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
    if sell_put.eligible:
        signal_service.emit(
            "sell_put_opportunity",
            "TQQQ 开仓 Sell Put",
            f"QQQ 三项条件满足，TQQQ 参考行权价 {sell_put.reference_strike}",
            "opportunity",
            market_date,
            stale=stale,
        )
    if risk.severity == "critical":
        signal_service.emit("ma200_break", "跌破牛熊分界线", risk.message, "critical", market_date, stale=stale)
    if series["VIX"].bars[-1].close >= Decimal("30"):
        signal_service.emit(
            "vix_high", "VIX 达到 30", "评估是否动用现金储备。", "warning", market_date, stale=stale
        )
    if core_decision.recommendation and core_decision.recommendation.actionable:
        core_signal = core_decision.recommendation
        signal_service.emit(
            f"core_buy_{core_signal.symbol.lower().replace('.', '_')}",
            f"{core_signal.symbol} 核心仓买入建议",
            f"{core_signal.symbol} 当前为核心仓相对优先缺口，建议金额 {core_signal.executable_amount}。",
            "opportunity",
            market_date,
            stale=stale,
        )
    if core_decision.rotation.actionable:
        rotation = core_decision.rotation
        signal_service.emit(
            "core_rotation_opportunity",
            f"核心仓轮换：{rotation.sell_symbol} → {rotation.buy_symbol}",
            f"相对偏离达到 {rotation.code} 档，建议等额轮换 {rotation.amount}。",
            "opportunity",
            market_date,
            stale=stale,
        )
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
            "个股趋势、RSI、市值与单日跌幅条件同时满足；成交仍由用户确认。",
            "opportunity",
            market_date,
            stale=stale,
        )
    club_wheel_opportunities = [
        decision for decision in club_wheel_decisions if decision.technical_eligible
    ]
    if club_wheel_opportunities:
        strongest = min(
            club_wheel_opportunities,
            key=lambda decision: (decision.change_fraction or ZERO, decision.symbol),
        )
        signal_service.emit(
            f"trillion_club_wheel_{strongest.symbol.lower().replace('.', '_').replace('-', '_')}",
            f"{strongest.symbol} 万亿俱乐部 Sell Put 机会",
            "个股趋势、RSI、单日跌幅与支撑位条件同时满足；需确认财报和实际期权成交。",
            "opportunity",
            market_date,
            stale=stale,
        )
    club_wheel_risks = [
        decision for decision in club_wheel_decisions if decision.high_risk_put_ids
    ]
    if club_wheel_risks:
        risky = club_wheel_risks[0]
        signal_service.emit(
            f"trillion_club_wheel_risk_{risky.symbol.lower().replace('.', '_').replace('-', '_')}",
            f"{risky.symbol} 个股车轮趋势破位",
            "个股连续两个完成交易日低于 SMA200，且现有车轮仓位面临行权或持股风险。",
            "critical",
            market_date,
            stale=stale,
        )

    sources = {value.source for value in series.values()}
    if session_quote is not None:
        sources.add(session_quote.source)
    return {
        "source": sources.pop() if len(sources) == 1 else "mixed",
        "as_of": market_date,
        "stale": stale,
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
            "vix": {"price": series["VIX"].bars[-1].close},
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
            "target": option_target,
            "current": option_committed,
            "available": max(option_target - option_committed, ZERO),
            "over": max(option_committed - option_target, ZERO),
        },
        "leaps_club": {
            "decisions": club_decisions,
            "unavailable": club_unavailable,
            "exclusions": sorted(TRILLION_CLUB_EXCLUSIONS),
        },
        "leaps_session": {
            "available": live_session_quote,
            "price": session_quote.price if session_quote else None,
            "previous_close": session_quote.previous_close if session_quote else qqq_closes[-1],
            "change_fraction": session_quote.change_fraction if session_quote else None,
            "quoted_at": session_quote.quoted_at if session_quote else None,
            "market_date": market_date,
            "session": session_quote.session if session_quote else "unavailable",
            "source": session_quote.source if session_quote else None,
        },
        "equities": equity_quotes,
        "core": core_payload,
    }


def _load_club_markets(
    provider: MarketDataProvider,
    market_date: date,
) -> tuple[list[ClubMarketState], list[dict]]:
    states: list[ClubMarketState] = []
    unavailable: list[dict] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_load_club_market, provider, symbol, market_date): symbol
            for symbol in TRILLION_CLUB_CANDIDATES
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                states.append(future.result())
            except (AttributeError, MarketDataError, OSError, KeyError, ValueError) as error:
                unavailable.append(
                    {
                        "symbol": symbol,
                        "name": TRILLION_CLUB_CANDIDATES[symbol],
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
    market_cap = provider.market_cap(symbol)
    if market_cap.source == "sample":
        raise MarketDataError(f"{symbol} 公开市值不可用")
    if market_cap.currency != "USD" or market_cap.value < TRILLION_USD:
        raise MarketDataError(f"{symbol} 当前公开美元市值未达 $1T")
    series = provider.daily_bars(symbol, 300)
    quote = provider.session_quote(symbol)
    bars = completed_daily_bars(series, quote)
    if len(bars) < 200:
        raise MarketDataError(f"{symbol} 完成日线不足 200 条")
    closes = [bar.close for bar in bars]
    market_cap_fresh = abs((market_date - market_cap.as_of).days) <= 200
    try:
        earnings = provider.earnings_date(symbol)
        next_earnings_date = (
            earnings.event_date if earnings.event_date >= market_date else None
        )
        earnings_available = earnings.source != "sample" and next_earnings_date is not None
    except (AttributeError, MarketDataError, OSError, KeyError, ValueError):
        next_earnings_date = None
        earnings_available = False
    return ClubMarketState(
        symbol=symbol,
        close=closes[-1],
        previous_close=closes[-2],
        ma200=simple_moving_average(closes, 200),
        rsi14=wilder_rsi(closes),
        current_price=quote.price,
        change_fraction=quote.change_fraction,
        live_quote=series.source != "sample" and quote.source != "sample",
        market_cap=market_cap.value,
        market_cap_as_of=market_cap.as_of,
        market_cap_currency=market_cap.currency,
        market_cap_live=market_cap.source != "sample" and market_cap_fresh,
        completed_sessions=len(bars),
        two_closes_below_ma200=(
            closes[-1] < simple_moving_average(closes, 200)
            and closes[-2] < simple_moving_average(closes[:-1], 200)
        ),
        supports=tuple(find_support_levels(bars, quote.price)[:4]),
        next_earnings_date=next_earnings_date,
        earnings_available=earnings_available,
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
            value = fixed_series.get(symbol) or provider.daily_bars(symbol, 5)
            if value.source == "sample":
                raise MarketDataError("公开行情不可用，未使用模拟价格估值")
            price = value.bars[-1].close
            for record in other_records:
                if record.symbol == symbol:
                    record.current_price = price
                    record.quote_source = value.source
                    record.quote_as_of = value.as_of
                    record.last_error = None
            for position in equity_positions:
                if position.symbol == symbol:
                    position.current_price = price
                    position.quote_source = value.source
                    position.quote_as_of = datetime.combine(value.as_of, datetime.min.time())
            results[symbol] = {
                "price": price,
                "source": value.source,
                "as_of": value.as_of,
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
            if matching_record is not None:
                matching_record.last_error = str(error)
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
            if quote.bid < 0 or quote.ask < quote.bid:
                raise MarketDataError("其他期权报价不可用")
            if abs((as_of - quote.quoted_at.date()).days) > 5:
                raise MarketDataError("其他期权报价已过期")
            record.current_price = quote.bid if record.direction == "long" else quote.ask
            record.quote_source = quote.source
            record.quote_as_of = quote.quoted_at.date()
            record.last_error = None
        except (MarketDataError, OSError) as error:
            record.last_error = str(error)
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
            if quote.bid <= 0 or quote.ask < quote.bid:
                raise MarketDataError("LEAPS 期权报价不可用")
            if abs((as_of - quote.quoted_at.date()).days) > 5:
                raise MarketDataError("LEAPS 期权报价已过期")
            position.quote_source = quote.source
            position.quote_bid = quote.bid
            position.quote_ask = quote.ask
            position.quote_last = quote.last
            position.quote_iv = quote.implied_volatility
            position.quote_as_of = quote.quoted_at
            position.peak_bid = max(position.peak_bid or quote.bid, quote.bid)
            position.current_price = quote.bid
        except (MarketDataError, OSError):
            continue
