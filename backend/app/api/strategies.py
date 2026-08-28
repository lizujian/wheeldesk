from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import CallAwayAction, CloseOptionAction, DateAction, PutOpenCreate
from app.services.wheel_cycles import WheelCycleService

router = APIRouter(prefix="/api/wheel", tags=["wheel"])


def cycle_payload(cycle):
    if cycle is None:
        return {"state": "waiting_put"}
    return {
        "id": cycle.id,
        "state": cycle.state,
        "opened_on": cycle.opened_on,
        "closed_on": cycle.closed_on,
        "put_expiration": cycle.put_expiration,
        "put_strike": cycle.put_strike,
        "put_premium": cycle.put_premium,
        "put_quantity": cycle.put_quantity,
        "share_quantity": cycle.share_quantity,
        "share_cost_total": cycle.share_cost_total,
        "adjusted_share_basis": cycle.adjusted_share_basis,
        "call_expiration": cycle.call_expiration,
        "call_strike": cycle.call_strike,
        "call_premium": cycle.call_premium,
        "call_quantity": cycle.call_quantity,
        "realized_profit": cycle.realized_profit,
    }


@router.get("/current")
def current(session: Session = Depends(get_session)):
    return cycle_payload(WheelCycleService(session).current())


@router.post("/puts", status_code=status.HTTP_201_CREATED)
def open_put(payload: PutOpenCreate, session: Session = Depends(get_session)):
    try:
        cycle = WheelCycleService(session).open_put(**payload.model_dump())
        return cycle_payload(cycle)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{cycle_id}/assign-put")
def assign_put(cycle_id: int, payload: DateAction, session: Session = Depends(get_session)):
    try:
        return cycle_payload(WheelCycleService(session).assign_put(cycle_id, payload.date))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{cycle_id}/expire-put")
def expire_put(cycle_id: int, payload: DateAction, session: Session = Depends(get_session)):
    try:
        return cycle_payload(WheelCycleService(session).expire_put(cycle_id, payload.date))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{cycle_id}/close-put")
def close_put(cycle_id: int, payload: CloseOptionAction, session: Session = Depends(get_session)):
    try:
        return cycle_payload(
            WheelCycleService(session).close_put(cycle_id, payload.date, payload.premium)
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{cycle_id}/calls", status_code=status.HTTP_201_CREATED)
def open_call(cycle_id: int, payload: PutOpenCreate, session: Session = Depends(get_session)):
    try:
        return cycle_payload(WheelCycleService(session).open_call(cycle_id, **payload.model_dump()))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{cycle_id}/expire-call")
def expire_call(cycle_id: int, payload: DateAction, session: Session = Depends(get_session)):
    try:
        return cycle_payload(WheelCycleService(session).expire_call(cycle_id, payload.date))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{cycle_id}/close-call")
def close_call(cycle_id: int, payload: CloseOptionAction, session: Session = Depends(get_session)):
    try:
        return cycle_payload(
            WheelCycleService(session).close_call(cycle_id, payload.date, payload.premium)
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/{cycle_id}/call-away")
def call_away(cycle_id: int, payload: CallAwayAction, session: Session = Depends(get_session)):
    try:
        return cycle_payload(WheelCycleService(session).call_away(cycle_id, payload.date))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
