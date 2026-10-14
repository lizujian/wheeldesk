from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.db_models import MarketDataSettings, PositionRecord, SignalRecord, UnmanagedPositionRecord, WheelCallLot, WheelPutLot
from app.market.base import MarketDataError
from app.market.factory import close_providers
from app.market.ibkr import IbkrMarketDataProvider
from app.market.ibkr_connection import IbkrConnection
from app.market.settings import MarketSettings, read_settings
from app.market.operations import market_operation

router = APIRouter(prefix="/api/settings/market", tags=["settings"])


@router.get("")
def get_settings(session: Session = Depends(get_session)):
    return read_settings(session).payload()


@router.put("")
@market_operation
def save_settings(payload: MarketSettings, session: Session = Depends(get_session)):
    previous = read_settings(session)
    changed = previous.config_key != payload.config_key or previous.club_symbols != payload.club_symbols
    row = session.get(MarketDataSettings, 1)
    if row is None:
        row = MarketDataSettings(id=1)
        session.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    if changed:
        # Prices keep their original provenance, but old advice cannot survive
        # a provider switch as executable advice.
        for model in (PositionRecord, UnmanagedPositionRecord, WheelPutLot, WheelCallLot):
            for record in session.scalars(select(model)):
                record.quote_quality = "stale"
        for signal in session.scalars(select(SignalRecord).where(SignalRecord.acknowledged.is_(False))):
            signal.acknowledged = True
    session.commit()
    if changed:
        close_providers()
    return payload.payload()


@router.post("/test")
def test_connection(payload: MarketSettings):
    if not payload.configured:
        return {"connected": False, "error": "请填写 IB Gateway 地址和端口，并启动、登录 Gateway", "vix_provider": "ibkr"}
    # A separate diagnostic client avoids colliding with a retained connection.
    client_id = payload.ibkr_client_id + 1 if payload.ibkr_client_id < 2147483647 else payload.ibkr_client_id - 1
    connection = IbkrConnection(payload.ibkr_host, payload.ibkr_port, client_id)
    try:
        return IbkrMarketDataProvider(connection).diagnostics()
    except MarketDataError as error:
        return {"connected": False, "error": str(error), "vix_provider": "ibkr"}
    finally:
        connection.close()
