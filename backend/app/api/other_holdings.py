from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import OtherHoldingClose, OtherHoldingCreate, OtherHoldingUpdate
from app.services.other_holdings import OtherHoldingService

router = APIRouter(prefix="/api/other-holdings", tags=["other-holdings"])


@router.get("")
def list_other_holdings(
    include_closed: bool = False, session: Session = Depends(get_session)
):
    return OtherHoldingService(session).listing(include_closed=include_closed)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_other_holding(
    payload: OtherHoldingCreate, session: Session = Depends(get_session)
):
    try:
        return OtherHoldingService(session).create(**payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.patch("/{record_id}")
def update_other_holding(
    record_id: int,
    payload: OtherHoldingUpdate,
    session: Session = Depends(get_session),
):
    try:
        return OtherHoldingService(session).update(
            record_id, **payload.model_dump(exclude_none=True)
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_other_holding(record_id: int, session: Session = Depends(get_session)):
    try:
        OtherHoldingService(session).delete(record_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{record_id}/close")
def close_other_holding(
    record_id: int,
    payload: OtherHoldingClose,
    session: Session = Depends(get_session),
):
    try:
        return OtherHoldingService(session).close(record_id, payload.date, payload.price)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
