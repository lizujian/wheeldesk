from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import DateAction, RebalanceCoreSale
from app.services.core_rebalancing import CoreRebalancingService
from app.services.rebalancing import RebalancingService

router = APIRouter(prefix="/api/rebalancing", tags=["rebalancing"])


@router.get("")
def snapshot(
    as_of: date = Query(default_factory=date.today),
    session: Session = Depends(get_session),
):
    try:
        return RebalancingService(session).evaluate(as_of)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/evaluate")
def evaluate(payload: DateAction, session: Session = Depends(get_session)):
    try:
        return RebalancingService(session).evaluate(payload.date)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/confirm-no-trade")
def confirm_no_trade(payload: DateAction, session: Session = Depends(get_session)):
    try:
        return RebalancingService(session).confirm_no_trade(payload.date)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/core-sale")
def core_sale(payload: RebalanceCoreSale, session: Session = Depends(get_session)):
    try:
        service = RebalancingService(session)
        before = service.evaluate(payload.date)
        if not before["core_decision"]["actionable"]:
            raise ValueError("当前没有可执行的核心仓再平衡卖出建议")
        sale = CoreRebalancingService(session).sell_fifo(
            payload.date, payload.quantity, payload.price, payload.symbol
        )
        return {"sale": sale, "snapshot": service.evaluate(payload.date)}
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
