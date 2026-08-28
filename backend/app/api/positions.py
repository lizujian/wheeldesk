from dataclasses import asdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.db_models import LedgerEvent, PositionRecord
from app.domain.leaps import (
    LeapsExitInputs,
    evaluate_leaps_equity_exit,
    evaluate_leaps_exit,
)
from app.domain.trillion_club import is_club_symbol
from app.domain.models import Bucket
from app.schemas import PositionClose, PositionCreate, PositionMark
from app.services.realized_cash import RealizedCashService
from app.services.portfolio_store import PortfolioStore

router = APIRouter(prefix="/api/positions", tags=["positions"])


def position_payload(position: PositionRecord) -> dict:
    cost = position.entry_price * position.quantity * position.multiplier
    value = position.current_price * position.quantity * position.multiplier
    unrealized = value - cost if position.status == "open" else None
    exit_decision = None
    if position.bucket == Bucket.LEAPS.value and position.expiration is not None:
        as_of = position.quote_as_of.date() if position.quote_as_of else date.today()
        exit_decision = asdict(
            evaluate_leaps_exit(
                LeapsExitInputs(
                    opened_on=position.opened_on,
                    expiration=position.expiration,
                    as_of=as_of,
                    entry_price=position.entry_price,
                    current_bid=position.quote_bid,
                )
            )
        )
    elif (
        position.bucket == Bucket.LEAPS.value
        and position.asset_type == "equity"
        and position.symbol == "QLD"
    ):
        as_of = position.quote_as_of.date() if position.quote_as_of else date.today()
        exit_decision = asdict(
            evaluate_leaps_equity_exit(
                opened_on=position.opened_on,
                as_of=as_of,
                entry_price=position.entry_price,
                current_price=position.current_price,
            )
        )
    return {
        "id": position.id,
        "rolled_from_position_id": position.rolled_from_position_id,
        "bucket": position.bucket,
        "symbol": position.symbol,
        "asset_type": position.asset_type,
        "direction": position.direction,
        "option_type": position.option_type,
        "quantity": position.quantity,
        "multiplier": position.multiplier,
        "entry_price": position.entry_price,
        "current_price": position.current_price,
        "current_value": value,
        "unrealized_profit": unrealized,
        "opened_on": position.opened_on,
        "expiration": position.expiration,
        "strike": position.strike,
        "delta": position.delta,
        "tranche": position.tranche,
        "leaps_category": (
            "club"
            if position.bucket == Bucket.LEAPS.value and is_club_symbol(position.symbol)
            else "qqq"
            if position.bucket == Bucket.LEAPS.value
            else None
        ),
        "underlying_entry_price": position.underlying_entry_price,
        "status": position.status,
        "closed_on": position.closed_on,
        "realized_profit": position.realized_profit,
        "total_loss_impact": cost if position.bucket == "leaps" else None,
        "quote_source": position.quote_source,
        "quote_bid": position.quote_bid,
        "quote_ask": position.quote_ask,
        "quote_last": position.quote_last,
        "quote_iv": position.quote_iv,
        "quote_as_of": position.quote_as_of,
        "peak_bid": position.peak_bid,
        "exit_decision": exit_decision,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_position(payload: PositionCreate, session: Session = Depends(get_session)):
    multiplier = 100 if payload.asset_type == "option" else 1
    if payload.bucket == Bucket.CORE:
        try:
            PortfolioStore(session).auto_fund_core(
                payload.entry_price * payload.quantity * multiplier,
                payload.opened_on,
            )
        except ValueError as error:
            session.rollback()
            raise HTTPException(status_code=409, detail=str(error)) from error
    position = PositionRecord(
        bucket=payload.bucket.value,
        symbol=payload.symbol.upper(),
        asset_type=payload.asset_type,
        direction=payload.direction,
        option_type=payload.option_type,
        quantity=payload.quantity,
        multiplier=multiplier,
        entry_price=payload.entry_price,
        current_price=payload.entry_price,
        opened_on=payload.opened_on,
        expiration=payload.expiration,
        strike=payload.strike,
        delta=payload.delta,
        tranche=payload.tranche,
        underlying_entry_price=None,
        entry_fees=0,
    )
    session.add(position)
    session.flush()
    session.add(
        LedgerEvent(
            event_type="position_open",
            bucket=payload.bucket.value,
            amount=0,
            occurred_on=payload.opened_on,
            details={
                "position_id": position.id,
                "symbol": position.symbol,
                **(
                    {"core_signal_code": payload.core_signal_code}
                    if payload.core_signal_code
                    else {}
                ),
            },
        )
    )
    session.commit()
    return position_payload(position)


@router.get("")
def list_positions(include_closed: bool = False, session: Session = Depends(get_session)):
    statement = select(PositionRecord).order_by(PositionRecord.opened_on.desc(), PositionRecord.id.desc())
    if not include_closed:
        statement = statement.where(PositionRecord.status == "open")
    return [position_payload(position) for position in session.scalars(statement)]


@router.patch("/{position_id}/mark")
def mark_position(position_id: int, payload: PositionMark, session: Session = Depends(get_session)):
    position = _open_position(session, position_id)
    position.current_price = payload.price
    session.commit()
    return position_payload(position)


@router.post("/{position_id}/close")
def close_position(position_id: int, payload: PositionClose, session: Session = Depends(get_session)):
    position = _open_position(session, position_id)
    if position.bucket == Bucket.CORE.value:
        raise HTTPException(
            status_code=409,
            detail="核心仓仅允许通过账户再平衡卖出",
        )
    sold_quantity = payload.quantity if payload.quantity is not None else position.quantity
    if sold_quantity > position.quantity:
        raise HTTPException(status_code=409, detail="卖出数量超过当前持仓")
    cost = position.entry_price * sold_quantity * position.multiplier
    proceeds = payload.price * sold_quantity * position.multiplier
    realized = proceeds - cost
    position.current_price = payload.price
    position.realized_profit = (position.realized_profit or Decimal("0")) + realized
    position.quantity -= sold_quantity
    if position.quantity == 0:
        position.exit_price = payload.price
        position.exit_fees = 0
        position.closed_on = payload.date
        position.status = "closed"
    event = LedgerEvent(
        event_type="position_close" if position.status == "closed" else "position_partial_close",
        bucket=position.bucket,
        amount=realized,
        occurred_on=payload.date,
        details={
            "position_id": position.id,
            "symbol": position.symbol,
            "quantity": float(sold_quantity),
            "price": float(payload.price),
        },
    )
    session.add(event)
    session.flush()
    if position.bucket == Bucket.LEAPS.value:
        note = (
            f"QLD 槽位 {position.tranche} 卖出"
            if position.asset_type == "equity"
            else f"QQQ LEAPS 槽位 {position.tranche} 卖出"
        )
        RealizedCashService(session).post(
            f"leaps-position-exit:{event.id}",
            Bucket.LEAPS,
            realized,
            payload.date,
            profit_source="leaps",
            note=note,
        )
    session.commit()
    return position_payload(position)


def _open_position(session: Session, position_id: int) -> PositionRecord:
    position = session.get(PositionRecord, position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="找不到持仓")
    if position.status != "open":
        raise HTTPException(status_code=409, detail="持仓已经平仓")
    return position
