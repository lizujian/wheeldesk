from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.signals import SignalService

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
def list_signals(
    include_acknowledged: bool = False,
    session: Session = Depends(get_session),
):
    return SignalService(session).list_recent(
        include_acknowledged=include_acknowledged,
    )


@router.post("/{signal_id}/acknowledge")
def acknowledge(signal_id: int, session: Session = Depends(get_session)):
    try:
        return SignalService(session).acknowledge(signal_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
