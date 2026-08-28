from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.redistribution import recommend_distribution
from app.schemas import (
    AmountAction,
    OtherHoldingsUpdate,
    PortfolioInitialize,
    RedistributionRequest,
    TransferCreate,
)
from app.services.portfolio_store import PortfolioStore

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.post("/initialize", status_code=status.HTTP_201_CREATED)
def initialize(payload: PortfolioInitialize, session: Session = Depends(get_session)):
    try:
        return PortfolioStore(session).initialize(
            payload.age, payload.opening_equity, payload.opening_date, payload.allocations
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/summary")
def summary(session: Session = Depends(get_session)):
    return PortfolioStore(session).summary()


@router.post("/other-holdings")
def update_other_holdings(
    payload: OtherHoldingsUpdate,
    session: Session = Depends(get_session),
):
    try:
        return PortfolioStore(session).update_other_holdings(payload.amount)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/deposits")
def deposit(payload: AmountAction, session: Session = Depends(get_session)):
    return PortfolioStore(session).deposit(payload.amount, payload.date, payload.note)


@router.post("/transfers")
def transfer(payload: TransferCreate, session: Session = Depends(get_session)):
    try:
        return PortfolioStore(session).transfer(
            payload.source, payload.target, payload.amount, payload.date, payload.note
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/redistribution")
def redistribution(payload: RedistributionRequest, session: Session = Depends(get_session)):
    store = PortfolioStore(session)
    profile = store.profile()
    if profile is None:
        raise HTTPException(status_code=409, detail="请先初始化账户")
    summary_value = store.summary()
    return recommend_distribution(
        payload.distributable_profit,
        summary_value["total_equity"],
        profile.age,
        store.balances(),
    )
