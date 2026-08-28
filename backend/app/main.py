from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    exit_positions,
    ibkr_import,
    ledger,
    market,
    other_holdings,
    portfolio,
    profit_ledger,
    rebalancing,
    positions,
    signals,
    strategies,
    system,
    wheel_portfolio,
)
from app.db import initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield

app = FastAPI(title="Wheel Monitor", version="0.1.0", lifespan=lifespan)
app.include_router(portfolio.router)
app.include_router(other_holdings.router)
app.include_router(profit_ledger.router)
app.include_router(market.router)
app.include_router(ledger.router)
app.include_router(strategies.router)
app.include_router(positions.router)
app.include_router(signals.router)
app.include_router(system.router)
app.include_router(exit_positions.router)
app.include_router(ibkr_import.router)
app.include_router(wheel_portfolio.router)
app.include_router(rebalancing.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "wheel-monitor"}
