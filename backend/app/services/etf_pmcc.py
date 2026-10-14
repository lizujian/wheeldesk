"""Move supported ETF option legs into PMCC without creating trades or cash."""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.db_models import BrokerImportRecord, LedgerEvent, PositionRecord, UnmanagedPositionRecord
from app.domain.leaps import ADDITIONAL_LEAPS_ETFS, LEAPS_CALL_WHEEL_CATEGORY
from app.domain.pmcc import PMCC_CATEGORIES, call_contract_key, share_covered_call_keys


def _retarget_imports(session, holding_id, entity_type, entity_id):
    for row in session.scalars(select(BrokerImportRecord).where(
        BrokerImportRecord.entity_type.in_({"unmanaged_position", "leaps_call_wheel"}),
        BrokerImportRecord.entity_id == holding_id,
    )):
        row.entity_type, row.entity_id = entity_type, entity_id


def promote_etf_long(session, holding, tranche):
    position = PositionRecord(
        bucket="leaps", symbol=holding.symbol, asset_type="option", direction="long", option_type="call",
        quantity=holding.quantity, multiplier=holding.multiplier, entry_price=holding.entry_price,
        current_price=holding.current_price if holding.current_price is not None else holding.entry_price,
        opened_on=holding.opened_on, expiration=holding.expiration, strike=holding.strike, tranche=tranche,
        quote_source=holding.quote_source, last_error=holding.last_error,
        quote_as_of=datetime.combine(holding.quote_as_of, datetime.min.time()) if holding.quote_as_of else None,
        quote_vendor=holding.quote_vendor, quote_quality=holding.quote_quality,
        quote_fetched_at=holding.quote_fetched_at, quote_market_as_of=holding.quote_market_as_of,
    )
    session.add(position)
    session.flush()
    _retarget_imports(session, holding.id, "position", position.id)
    session.add(LedgerEvent(event_type="strategy_reclassification", bucket="leaps", amount=0,
        occurred_on=date.today(), details={"symbol": holding.symbol, "from_unmanaged_id": holding.id,
                                         "position_id": position.id}))
    session.delete(holding)
    session.flush()
    return position


def reclassify_etf_pmcc(session):
    changed = False
    for holding in list(session.scalars(select(UnmanagedPositionRecord).where(
        UnmanagedPositionRecord.symbol.in_(ADDITIONAL_LEAPS_ETFS), UnmanagedPositionRecord.category == "other",
        UnmanagedPositionRecord.status == "open", UnmanagedPositionRecord.asset_type == "option",
        UnmanagedPositionRecord.direction == "long", UnmanagedPositionRecord.option_type == "call",
    ).order_by(UnmanagedPositionRecord.opened_on, UnmanagedPositionRecord.id))):
        if any(value is None for value in (holding.opened_on, holding.expiration, holding.strike, holding.entry_price)) or holding.quantity <= 0:
            continue
        existing = list(session.scalars(select(PositionRecord).where(
            PositionRecord.bucket == "leaps", PositionRecord.status == "open", PositionRecord.symbol == holding.symbol,
        )))
        # An existing lot of the same contract needs explicit reconciliation.
        if any(row.expiration == holding.expiration and row.strike == holding.strike for row in existing):
            continue
        used = {row.tranche for row in existing}
        slot = next((slot for slot in (1, 2) if slot not in used), None)
        if slot is None:
            continue
        promote_etf_long(session, holding, slot)
        changed = True

    calls = list(session.scalars(select(UnmanagedPositionRecord).where(
        UnmanagedPositionRecord.symbol.in_(ADDITIONAL_LEAPS_ETFS), UnmanagedPositionRecord.status == "open",
        UnmanagedPositionRecord.asset_type == "option", UnmanagedPositionRecord.direction == "short",
        UnmanagedPositionRecord.option_type == "call",
    ).order_by(UnmanagedPositionRecord.opened_on, UnmanagedPositionRecord.id)))
    shares = {}
    for row in session.scalars(select(UnmanagedPositionRecord).where(
        UnmanagedPositionRecord.status == "open", UnmanagedPositionRecord.asset_type == "equity",
        UnmanagedPositionRecord.direction == "long", UnmanagedPositionRecord.symbol.in_(ADDITIONAL_LEAPS_ETFS),
    )):
        shares[row.symbol] = shares.get(row.symbol, Decimal(0)) + row.quantity
    share_calls = share_covered_call_keys(calls, shares)
    used = {}
    for call in calls:
        if call.category in PMCC_CATEGORIES and call.linked_position_id is not None:
            used[call.linked_position_id] = used.get(call.linked_position_id, Decimal(0)) + call.quantity
    positions = list(session.scalars(select(PositionRecord).where(
        PositionRecord.bucket == "leaps", PositionRecord.status == "open", PositionRecord.asset_type == "option",
        PositionRecord.direction == "long", PositionRecord.option_type == "call",
        PositionRecord.symbol.in_(ADDITIONAL_LEAPS_ETFS),
    ).order_by(PositionRecord.opened_on, PositionRecord.id)))
    for call in calls:
        if call.category != "other" or call_contract_key(call) in share_calls:
            continue
        candidate = next((row for row in positions if row.symbol == call.symbol
            and row.expiration is not None and call.expiration is not None and row.expiration > call.expiration
            and (call.opened_on is None or row.opened_on <= call.opened_on)
            and row.quantity - used.get(row.id, Decimal(0)) >= call.quantity), None)
        if candidate is None:
            continue
        call.category, call.linked_position_id = LEAPS_CALL_WHEEL_CATEGORY, candidate.id
        used[candidate.id] = used.get(candidate.id, Decimal(0)) + call.quantity
        _retarget_imports(session, call.id, "leaps_call_wheel", call.id)
        changed = True
    session.flush()
    return changed
