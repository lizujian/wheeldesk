from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import (
    DateAction,
    WheelCallAway,
    WheelCallCreate,
    WheelCallUpdate,
    WheelOptionClose,
    WheelPutAssign,
    WheelPutCreate,
    WheelPutUpdate,
    WheelVoidRequest,
)
from app.services.wheel_portfolio import WheelPortfolioService

router = APIRouter(prefix="/api/wheel", tags=["wheel-portfolio"])


def _mutate(session: Session, action):
    service = WheelPortfolioService(session)
    try:
        action(service)
        return service.overview()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/overview")
def overview(session: Session = Depends(get_session)):
    return WheelPortfolioService(session).overview()


@router.post("/portfolio/puts", status_code=status.HTTP_201_CREATED)
def open_put(payload: WheelPutCreate, session: Session = Depends(get_session)):
    return _mutate(session, lambda service: service.open_put(**payload.model_dump()))


@router.patch("/portfolio/puts/{put_id}")
def edit_put(put_id: int, payload: WheelPutUpdate, session: Session = Depends(get_session)):
    values = payload.model_dump(exclude_none=True)
    return _mutate(session, lambda service: service.edit_put(put_id, **values))


@router.post("/portfolio/puts/{put_id}/close")
def close_put(put_id: int, payload: WheelOptionClose, session: Session = Depends(get_session)):
    return _mutate(
        session,
        lambda service: service.close_put(put_id, payload.date, payload.premium),
    )


@router.post("/portfolio/puts/{put_id}/expire")
def expire_put(put_id: int, payload: DateAction, session: Session = Depends(get_session)):
    return _mutate(session, lambda service: service.expire_put(put_id, payload.date))


@router.post("/portfolio/puts/{put_id}/assign")
def assign_put(put_id: int, payload: WheelPutAssign, session: Session = Depends(get_session)):
    return _mutate(
        session,
        lambda service: service.assign_put(put_id, payload.date, payload.contracts),
    )


@router.post("/portfolio/shares/{share_id}/calls", status_code=status.HTTP_201_CREATED)
def open_call(share_id: int, payload: WheelCallCreate, session: Session = Depends(get_session)):
    return _mutate(
        session,
        lambda service: service.open_call(share_id, **payload.model_dump()),
    )


@router.patch("/portfolio/calls/{call_id}")
def edit_call(call_id: int, payload: WheelCallUpdate, session: Session = Depends(get_session)):
    values = payload.model_dump(exclude_none=True)
    return _mutate(session, lambda service: service.edit_call(call_id, **values))


@router.post("/portfolio/calls/{call_id}/close")
def close_call(call_id: int, payload: WheelOptionClose, session: Session = Depends(get_session)):
    return _mutate(
        session,
        lambda service: service.close_call(call_id, payload.date, payload.premium),
    )


@router.post("/portfolio/calls/{call_id}/expire")
def expire_call(call_id: int, payload: DateAction, session: Session = Depends(get_session)):
    return _mutate(session, lambda service: service.expire_call(call_id, payload.date))


@router.post("/portfolio/calls/{call_id}/call-away")
def call_away(call_id: int, payload: WheelCallAway, session: Session = Depends(get_session)):
    return _mutate(session, lambda service: service.call_away(call_id, payload.date))


@router.post("/portfolio/puts/{put_id}/void")
def void_put(put_id: int, payload: WheelVoidRequest, session: Session = Depends(get_session)):
    return _mutate(session, lambda service: service.void_put(put_id, payload.reason))


@router.post("/portfolio/puts/{put_id}/void-chain")
def void_chain(put_id: int, payload: WheelVoidRequest, session: Session = Depends(get_session)):
    return _mutate(session, lambda service: service.void_chain(put_id, payload.reason))
