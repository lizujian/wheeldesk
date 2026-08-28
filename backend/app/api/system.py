from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import ResetDataRequest
from app.services.reset import ResetService

router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/reset")
def reset_data(_: ResetDataRequest, session: Session = Depends(get_session)):
    ResetService(session).reset_all()
    return {"status": "reset"}
