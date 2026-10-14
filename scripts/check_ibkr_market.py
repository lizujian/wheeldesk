#!/usr/bin/env python3
"""Read-only IBKR diagnostics. Does not change settings, holdings or ledger."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db import engine
from app.db_models import PositionRecord, UnmanagedPositionRecord, WheelPutLot
from app.market.base import MarketDataError
from app.market.ibkr import IbkrMarketDataProvider
from app.market.ibkr_connection import IbkrConnection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4001)
    parser.add_argument("--client-id", type=int, default=73)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--contracts", action="store_true")
    args = parser.parse_args()
    connection = IbkrConnection(args.host, args.port, args.client_id)
    provider = IbkrMarketDataProvider(connection)
    result = {}
    try:
        result.update(provider.diagnostics())
        if args.history:
            result["history"] = {}
            for symbol in ("QQQ", "VIX"):
                series = provider.daily_bars(symbol)
                result["history"][symbol] = {"bars": len(series.bars), "source": series.source, "as_of": series.as_of, "close": series.bars[-1].close}
        if args.contracts:
            contracts = set()
            with Session(engine) as session:
                for model in (PositionRecord, UnmanagedPositionRecord):
                    for row in session.scalars(select(model).where(model.asset_type == "option", model.status == "open")):
                        if row.expiration and row.strike and row.option_type:
                            contracts.add((row.symbol, row.option_type, row.expiration, row.strike))
                for row in session.scalars(select(WheelPutLot).where(WheelPutLot.state == "open")):
                    contracts.add((row.symbol, "put", row.expiration, row.strike))
            provider.prefetch_options(contracts)
            result["contracts"] = []
            for contract in sorted(contracts):
                try:
                    result["contracts"].append(asdict(provider.option_quote(*contract)))
                except MarketDataError as error:
                    result["contracts"].append({"contract": [str(x) for x in contract], "error": str(error)})
    except MarketDataError as error:
        result["error"] = str(error)
    finally:
        connection.close()
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    return 0 if result.get("connected") and not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
