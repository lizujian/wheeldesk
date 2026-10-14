"""Compare current broker quantities without changing the accounting ledger."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.db_models import PositionRecord, UnmanagedPositionRecord, WheelCallLot, WheelPutLot, WheelShareLot


def reconcile_positions(session, connection):
    def key(symbol, asset_type, right=None, expiry=None, strike=None):
        symbol = {"BRK B": "BRK.B", "BRK-B": "BRK.B"}.get(symbol, symbol)
        return (symbol, asset_type, (right or "").lower(), str(expiry or ""),
                Decimal(str(strike)) if strike is not None else None)
    ledger, broker = defaultdict(Decimal), defaultdict(Decimal)
    for model in (PositionRecord, UnmanagedPositionRecord):
        for row in session.scalars(select(model).where(model.status == "open")):
            identity = key(row.symbol, row.asset_type, row.option_type, row.expiration, row.strike)
            ledger[identity] += row.quantity * (-1 if row.direction == "short" else 1)
    for put in session.scalars(select(WheelPutLot).where(WheelPutLot.state == "open")):
        ledger[key(put.symbol, "option", "put", put.expiration, put.strike)] -= put.open_quantity
    for share in session.scalars(select(WheelShareLot).where(WheelShareLot.remaining_quantity > 0)):
        put = session.get(WheelPutLot, share.put_lot_id)
        if put:
            ledger[key(put.symbol, "equity")] += share.remaining_quantity
    for call in session.scalars(select(WheelCallLot).where(WheelCallLot.state == "open")):
        share = session.get(WheelShareLot, call.share_lot_id)
        put = session.get(WheelPutLot, share.put_lot_id) if share else None
        if put:
            ledger[key(put.symbol, "option", "call", call.expiration, call.strike)] -= call.quantity
    rows = [row for row in connection.call("positions") if row["quantity"]]
    unsupported = 0
    for row in rows:
        c = row["contract"]
        if c.secType not in {"STK", "OPT"} or c.currency != "USD":
            unsupported += 1
            continue
        if c.secType == "OPT":
            try:
                expiry = datetime.strptime(c.lastTradeDateOrContractMonth[:8], "%Y%m%d").date()
            except ValueError:
                unsupported += 1
                continue
            if c.multiplier != "100":
                unsupported += 1
                continue
            identity = key(c.symbol, "option", {"C": "call", "P": "put"}.get(c.right), expiry, c.strike)
        else:
            identity = key(c.symbol, "equity")
        broker[identity] += Decimal(str(row["quantity"]))
    differences = []
    matched = 0
    for identity in sorted(ledger.keys() | broker.keys()):
        if ledger[identity] == broker[identity]:
            if ledger[identity]:
                matched += 1
            continue
        symbol, asset_type, right, expiry, strike = identity
        differences.append({"symbol": symbol, "asset_type": asset_type, "option_type": right or None,
            "expiration": expiry or None, "strike": strike,
            "ledger_quantity": ledger[identity], "broker_quantity": broker[identity]})
    return {"as_of": datetime.now(timezone.utc), "broker_position_count": len(rows),
            "matched_count": matched, "unsupported_count": unsupported,
            "differences": differences, "ledger_updated": False}
