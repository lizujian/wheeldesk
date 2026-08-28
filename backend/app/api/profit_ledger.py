from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import ProfitAllocationCreate, ProfitEntryDelete, ProfitRealizedCreate
from app.services.profit_ledger import ProfitLedgerService

router = APIRouter(prefix="/api/profit-ledger", tags=["profit-ledger"])


@router.get("")
def snapshot(session: Session = Depends(get_session)):
    return ProfitLedgerService(session).snapshot()


@router.post("/realized", status_code=status.HTTP_201_CREATED)
def record_realized(payload: ProfitRealizedCreate, session: Session = Depends(get_session)):
    try:
        return ProfitLedgerService(session).record_realized(**payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/allocations", status_code=status.HTTP_201_CREATED)
def record_allocation(payload: ProfitAllocationCreate, session: Session = Depends(get_session)):
    try:
        return ProfitLedgerService(session).record_allocation(**payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/entries/{entry_id}/delete")
def delete_entry(
    entry_id: str,
    _payload: ProfitEntryDelete,
    session: Session = Depends(get_session),
):
    try:
        return ProfitLedgerService(session).delete_manual(entry_id)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
