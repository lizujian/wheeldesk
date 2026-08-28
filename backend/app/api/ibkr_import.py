from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import BrokerImportConfirm, BrokerReportPayload
from app.services.ibkr_import import IbkrImportService

router = APIRouter(prefix="/api/imports/ibkr", tags=["ibkr-import"])


@router.post("/preview")
def preview(payload: BrokerReportPayload, session: Session = Depends(get_session)):
    try:
        return IbkrImportService(session).preview(payload.filename, payload.content)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/confirm")
def confirm(payload: BrokerImportConfirm, session: Session = Depends(get_session)):
    try:
        return IbkrImportService(session).confirm(
            payload.filename,
            payload.content,
            payload.selected_fingerprints,
            payload.overrides,
        )
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/auto")
def auto_import(payload: BrokerReportPayload, session: Session = Depends(get_session)):
    try:
        return IbkrImportService(session).import_all(payload.filename, payload.content)
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/history")
def history(session: Session = Depends(get_session)):
    return IbkrImportService(session).history()
