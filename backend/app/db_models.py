from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LedgerEvent(Base):
    __tablename__ = "ledger_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    bucket: Mapped[str] = mapped_column(String(30), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reverses_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("ledger_events.id"), nullable=True, unique=True
    )
    wheel_cycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("wheel_cycles.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WheelCycle(Base):
    __tablename__ = "wheel_cycles"

    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(String(30), default="put_open", index=True)
    opened_on: Mapped[date] = mapped_column(Date)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    put_expiration: Mapped[date] = mapped_column(Date)
    put_strike: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    put_premium: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    put_quantity: Mapped[int] = mapped_column(Integer)
    put_fees: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    put_premium_net: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    share_quantity: Mapped[int] = mapped_column(Integer, default=0)
    share_cost_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    call_expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    call_strike: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    call_premium: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    call_quantity: Mapped[int] = mapped_column(Integer, default=0)
    call_fees: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    call_premium_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    realized_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    @property
    def adjusted_share_basis(self) -> Decimal | None:
        if not self.share_quantity:
            return None
        remaining_cost = self.share_cost_total - self.call_premium_net
        return (remaining_cost / Decimal(self.share_quantity)).quantize(Decimal("0.01"))


class WheelRound(Base):
    __tablename__ = "wheel_rounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    opened_on: Mapped[date] = mapped_column(Date)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    realized_profit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WheelPutLot(Base):
    __tablename__ = "wheel_put_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("wheel_rounds.id"), index=True)
    rolled_from_put_id: Mapped[int | None] = mapped_column(
        ForeignKey("wheel_put_lots.id"), nullable=True, unique=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), default="TQQQ", server_default="TQQQ", index=True)
    batch_number: Mapped[int] = mapped_column(Integer, index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    expiration: Mapped[date] = mapped_column(Date, index=True)
    strike: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    premium: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    quantity: Mapped[int] = mapped_column(Integer)
    open_quantity: Mapped[int] = mapped_column(Integer)
    assigned_contracts: Mapped[int] = mapped_column(Integer, default=0)
    entry_tqqq_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    earnings_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    state: Mapped[str] = mapped_column(String(20), default="open", index=True)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    close_premium: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    realized_profit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    quote_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quote_bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_last: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_iv: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    quote_as_of: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    theoretical_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    theoretical_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    theoretical_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    captured_fraction: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    early_close_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    early_close_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def collateral(self) -> Decimal:
        return (self.strike * Decimal("100") * self.open_quantity).quantize(Decimal("0.01"))


class WheelShareLot(Base):
    __tablename__ = "wheel_share_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    put_lot_id: Mapped[int] = mapped_column(ForeignKey("wheel_put_lots.id"), index=True)
    assigned_on: Mapped[date] = mapped_column(Date, index=True)
    assignment_strike: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    original_quantity: Mapped[int] = mapped_column(Integer)
    remaining_quantity: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="held", index=True)
    realized_profit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    @property
    def capital(self) -> Decimal:
        return (self.assignment_strike * self.remaining_quantity).quantize(Decimal("0.01"))


class WheelCallLot(Base):
    __tablename__ = "wheel_call_lots"

    id: Mapped[int] = mapped_column(primary_key=True)
    share_lot_id: Mapped[int] = mapped_column(ForeignKey("wheel_share_lots.id"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    expiration: Mapped[date] = mapped_column(Date, index=True)
    strike: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    premium: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    quantity: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="open", index=True)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    close_premium: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    realized_profit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    quote_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quote_bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_last: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_iv: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    quote_as_of: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SignalRecord(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("code", "market_date", name="uq_signal_market_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(20), index=True)
    market_date: Mapped[date] = mapped_column(Date, index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PortfolioProfile(Base):
    __tablename__ = "portfolio_profile"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    age: Mapped[int] = mapped_column(Integer)
    opening_equity: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    opening_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    last_rebalanced_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    other_holdings_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), server_default="0"
    )


class BucketBalance(Base):
    __tablename__ = "bucket_balances"

    bucket: Mapped[str] = mapped_column(String(30), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))


class PositionRecord(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    rolled_from_position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id"), nullable=True, unique=True, index=True
    )
    bucket: Mapped[str] = mapped_column(String(30), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    asset_type: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(10), default="long")
    option_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    multiplier: Mapped[int] = mapped_column(Integer, default=1)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    current_price: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    opened_on: Mapped[date] = mapped_column(Date)
    expiration: Mapped[date | None] = mapped_column(Date, nullable=True)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    delta: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    tranche: Mapped[int | None] = mapped_column(Integer, nullable=True)
    underlying_entry_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True
    )
    entry_fees: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    exit_fees: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    realized_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    quote_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quote_bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_last: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_iv: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    quote_as_of: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    peak_bid: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)


class OtherHoldingRecord(Base):
    __tablename__ = "other_holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quote_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quote_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class UnmanagedPositionRecord(Base):
    __tablename__ = "unmanaged_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(30), default="other", index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    asset_type: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10), default="long")
    option_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    multiplier: Mapped[int] = mapped_column(Integer, default=1)
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    opened_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    realized_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    quote_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    quote_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    legacy_other_holding_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class RealizedCashPosting(Base):
    __tablename__ = "realized_cash_postings"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    source_bucket: Mapped[str] = mapped_column(String(30), index=True)
    posted_bucket: Mapped[str] = mapped_column(String(30), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExitPositionRecord(Base):
    __tablename__ = "exit_positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    position_type: Mapped[str] = mapped_column(String(20), index=True)
    current_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    target_value: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)
    recovered_cash: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProfitLedgerEntry(Base):
    __tablename__ = "profit_ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_type: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BrokerImportRecord(Base):
    __tablename__ = "broker_import_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    section: Mapped[str] = mapped_column(String(80), index=True)
    row_index: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(40), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
