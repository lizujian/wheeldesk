from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.ledger import LedgerService

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


@router.get("/events")
def events(session: Session = Depends(get_session)):
    return LedgerService(session).list_events()


@router.post("/events/{event_id}/reverse")
def reverse(event_id: int, payload: dict, session: Session = Depends(get_session)):
    try:
        return LedgerService(session).reverse(event_id, payload["date"], payload.get("note", ""))
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
