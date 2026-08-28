from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import (
    ExitPositionCompleteExit,
    ExitPositionCreate,
    ExitPositionPartialExit,
    ExitPositionUpdate,
)
from app.services.exit_positions import ExitPositionService

router = APIRouter(prefix="/api/exit-positions", tags=["exit-positions"])


@router.get("")
def list_exit_positions(include_exited: bool = True, session: Session = Depends(get_session)):
    service = ExitPositionService(session)
    records = service.list_records(include_exited=include_exited)
    return {
        "records": [service.payload(record) for record in records],
        "summary": service.summary(records),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_exit_position(payload: ExitPositionCreate, session: Session = Depends(get_session)):
    service = ExitPositionService(session)
    try:
        record = service.create(**payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return service.payload(record)


@router.patch("/{record_id}")
def update_exit_position(
    record_id: int,
    payload: ExitPositionUpdate,
    session: Session = Depends(get_session),
):
    service = ExitPositionService(session)
    try:
        record = service.update(record_id, **payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return service.payload(record)


@router.post("/{record_id}/partial-exit")
def partial_exit(
    record_id: int,
    payload: ExitPositionPartialExit,
    session: Session = Depends(get_session),
):
    service = ExitPositionService(session)
    try:
        record = service.partial_exit(record_id, **payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return service.payload(record)


@router.post("/{record_id}/complete-exit")
def complete_exit(
    record_id: int,
    payload: ExitPositionCompleteExit,
    session: Session = Depends(get_session),
):
    service = ExitPositionService(session)
    try:
        record = service.complete_exit(record_id, **payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return service.payload(record)
