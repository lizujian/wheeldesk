"""Pure PMCC state and risk-budget calculations.

The database stores the two PMCC legs separately because broker statements
report them separately.  This module is the read-model boundary that turns a
Long LEAPS leg and its linked Short Call leg into one risk-managed strategy.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")

PMCC_CATEGORY = "pmcc"
LEGACY_PMCC_CATEGORY = "leaps_call_wheel"
PMCC_CATEGORIES = frozenset({PMCC_CATEGORY, LEGACY_PMCC_CATEGORY})

PMCC_TOTAL_FRACTION = Decimal("0.25")
PMCC_QQQ_FRACTION = Decimal("0.10")
PMCC_INDIVIDUAL_FRACTION = Decimal("0.15")
PMCC_SINGLE_STOCK_CAP = Decimal("0.03")
QQQ_PMCC_SLOT_FRACTION = Decimal("0.02")
INDIVIDUAL_PMCC_SLOT_FRACTION = Decimal("0.015")
SHORT_CALL_ROLL_DTE = 21
LONG_LEAPS_ROLL_DTE = 90


@dataclass(frozen=True)
class PMCCBudget:
    total_equity: Decimal
    total_target: Decimal
    qqq_target: Decimal
    individual_target: Decimal
    individual_symbol_cap: Decimal
    qqq_slot_target: Decimal
    individual_slot_target: Decimal

    def payload(self) -> dict:
        return {
            "total_equity": self.total_equity,
            "total_target": self.total_target,
            "qqq_target": self.qqq_target,
            "individual_target": self.individual_target,
            "individual_symbol_cap": self.individual_symbol_cap,
            "qqq_slot_target": self.qqq_slot_target,
            "individual_slot_target": self.individual_slot_target,
        }


@dataclass(frozen=True)
class PMCCState:
    symbol: str
    long_position_id: int | None
    short_call_ids: tuple[int, ...]
    status: str
    reason: str
    long_quantity: Decimal
    short_quantity: Decimal
    covered_contracts: Decimal
    coverage_ratio: Decimal
    long_debit: Decimal
    short_premium_received: Decimal
    short_buyback_cost: Decimal
    short_call_pnl: Decimal
    net_cash_flow: Decimal
    net_debit: Decimal
    maximum_loss: Decimal
    long_current_value: Decimal
    short_current_value: Decimal
    current_exposure: Decimal
    long_expiration: date | None
    short_expiration: date | None
    long_dte: int | None
    short_dte: int | None
    short_strike: Decimal | None
    underlying_price: Decimal | None
    assignment_risk: bool
    needs_roll: bool

    def payload(self) -> dict:
        return {
            "symbol": self.symbol,
            "long_position_id": self.long_position_id,
            "short_call_ids": list(self.short_call_ids),
            "status": self.status,
            "reason": self.reason,
            "long_quantity": self.long_quantity,
            "short_quantity": self.short_quantity,
            "covered_contracts": self.covered_contracts,
            "coverage_ratio": self.coverage_ratio,
            "long_debit": self.long_debit,
            "short_premium_received": self.short_premium_received,
            "short_buyback_cost": self.short_buyback_cost,
            "short_call_pnl": self.short_call_pnl,
            "net_cash_flow": self.net_cash_flow,
            "net_debit": self.net_debit,
            "maximum_loss": self.maximum_loss,
            "long_current_value": self.long_current_value,
            "short_current_value": self.short_current_value,
            "current_exposure": self.current_exposure,
            "long_expiration": self.long_expiration,
            "short_expiration": self.short_expiration,
            "long_dte": self.long_dte,
            "short_dte": self.short_dte,
            "short_strike": self.short_strike,
            "underlying_price": self.underlying_price,
            "assignment_risk": self.assignment_risk,
            "needs_roll": self.needs_roll,
        }


def pmcc_budget(total_equity: Decimal) -> PMCCBudget:
    total_equity = max(total_equity, ZERO).quantize(CENT)
    return PMCCBudget(
        total_equity=total_equity,
        total_target=(total_equity * PMCC_TOTAL_FRACTION).quantize(CENT),
        qqq_target=(total_equity * PMCC_QQQ_FRACTION).quantize(CENT),
        individual_target=(total_equity * PMCC_INDIVIDUAL_FRACTION).quantize(CENT),
        individual_symbol_cap=(total_equity * PMCC_SINGLE_STOCK_CAP).quantize(CENT),
        qqq_slot_target=(total_equity * QQQ_PMCC_SLOT_FRACTION).quantize(CENT),
        individual_slot_target=(
            total_equity * INDIVIDUAL_PMCC_SLOT_FRACTION
        ).quantize(CENT),
    )


def is_pmcc_long(position) -> bool:
    return (
        getattr(position, "bucket", None) == "leaps"
        and getattr(position, "status", "open") == "open"
        and getattr(position, "direction", "long") == "long"
        and (
            (
                getattr(position, "asset_type", None) == "option"
                and getattr(position, "option_type", None) == "call"
            )
            or (
                getattr(position, "asset_type", None) == "equity"
                and getattr(position, "symbol", "").upper() == "QLD"
            )
        )
    )


def is_pmcc_short_call(record) -> bool:
    return (
        getattr(record, "status", "open") == "open"
        and getattr(record, "asset_type", None) == "option"
        and getattr(record, "direction", None) == "short"
        and getattr(record, "option_type", None) == "call"
        and getattr(record, "category", None) in PMCC_CATEGORIES
    )


def build_pmcc_states(
    long_positions: Iterable,
    short_calls: Iterable,
    *,
    as_of: date,
    underlying_prices: Mapping[str, Decimal] | None = None,
) -> list[PMCCState]:
    positions = [position for position in long_positions if is_pmcc_long(position)]
    calls = [call for call in short_calls if is_pmcc_short_call(call)]
    linked_calls: dict[int, list] = {}
    unlinked_calls: list = []
    for call in calls:
        if call.linked_position_id is not None:
            linked_calls.setdefault(int(call.linked_position_id), []).append(call)
        else:
            unlinked_calls.append(call)

    states = [
        _state_for_long(
            position,
            linked_calls.pop(position.id, []),
            as_of=as_of,
            underlying_price=(underlying_prices or {}).get(position.symbol),
        )
        for position in sorted(positions, key=lambda item: (item.symbol, item.id))
    ]
    states.extend(
        _state_for_unlinked_call(
            call,
            as_of=as_of,
            underlying_price=(underlying_prices or {}).get(call.symbol),
        )
        for call in [
            *unlinked_calls,
            *(call for calls_for_position in linked_calls.values() for call in calls_for_position),
        ]
    )
    return sorted(
        states,
        key=lambda state: (state.symbol, state.long_position_id is None, state.long_position_id or 0),
    )


def summarize_pmcc(states: Iterable[PMCCState], total_equity: Decimal) -> dict:
    states = list(states)
    budget = pmcc_budget(total_equity)
    long_states = {
        state.long_position_id: state
        for state in states
        if state.long_position_id is not None
    }
    qqq_states = [
        state for state in long_states.values() if state.symbol.upper() in {"QQQ", "QLD"}
    ]
    individual_states = [
        state for state in long_states.values() if state.symbol.upper() not in {"QQQ", "QLD"}
    ]
    by_symbol: dict[str, dict] = {}
    for state in individual_states:
        item = by_symbol.setdefault(
            state.symbol,
            {"symbol": state.symbol, "committed": ZERO, "maximum_loss": ZERO, "states": 0},
        )
        item["committed"] += state.long_debit
        item["maximum_loss"] += state.maximum_loss
        item["states"] += 1
    for item in by_symbol.values():
        item["committed"] = item["committed"].quantize(CENT)
        item["maximum_loss"] = item["maximum_loss"].quantize(CENT)
        item["over_cap"] = item["committed"] > budget.individual_symbol_cap

    def totals(group: list[PMCCState]) -> dict:
        return {
            "committed": sum((state.long_debit for state in group), ZERO).quantize(CENT),
            "maximum_loss": sum((state.maximum_loss for state in group), ZERO).quantize(CENT),
            "net_cash_flow": sum((state.net_cash_flow for state in group), ZERO).quantize(CENT),
            "current_exposure": sum((state.current_exposure for state in group), ZERO).quantize(CENT),
            "states": len(group),
        }

    qqq = totals(qqq_states)
    individual = totals(individual_states)
    all_long = totals(list(long_states.values()))
    return {
        "budget": budget.payload(),
        "qqq": {**qqq, "target": budget.qqq_target, "available": max(budget.qqq_target - qqq["committed"], ZERO).quantize(CENT), "over": max(qqq["committed"] - budget.qqq_target, ZERO).quantize(CENT)},
        "individual": {**individual, "target": budget.individual_target, "available": max(budget.individual_target - individual["committed"], ZERO).quantize(CENT), "over": max(individual["committed"] - budget.individual_target, ZERO).quantize(CENT), "symbols": by_symbol},
        "total": {**all_long, "target": budget.total_target, "available": max(budget.total_target - all_long["committed"], ZERO).quantize(CENT), "over": max(all_long["committed"] - budget.total_target, ZERO).quantize(CENT)},
        "uncovered_count": sum(state.status == "uncovered" for state in states),
        "assignment_risk_count": sum(state.assignment_risk for state in states),
        "needs_roll_count": sum(state.needs_roll for state in states),
        "states": [state.payload() for state in states],
    }


def _state_for_long(position, calls: list, *, as_of: date, underlying_price: Decimal | None) -> PMCCState:
    covered_contracts = (
        position.quantity
        if position.asset_type == "option"
        else (position.quantity / HUNDRED)
    )
    long_debit = _money(position.entry_price * position.quantity * position.multiplier)
    long_value = _money((position.current_price or ZERO) * position.quantity * position.multiplier)
    short_quantity = sum((call.quantity for call in calls), ZERO)
    short_premium = _money(
        sum(
            ((call.entry_price or ZERO) * call.quantity * call.multiplier for call in calls),
            ZERO,
        )
    )
    short_buyback = _money(
        sum(
            ((call.current_price or ZERO) * call.quantity * call.multiplier for call in calls),
            ZERO,
        )
    )
    return _compose_state(
        symbol=position.symbol,
        long_position_id=position.id,
        short_calls=calls,
        long_quantity=position.quantity,
        short_quantity=short_quantity,
        covered_contracts=covered_contracts,
        long_debit=long_debit,
        long_current_value=long_value,
        long_expiration=position.expiration,
        as_of=as_of,
        underlying_price=underlying_price,
        short_premium=short_premium,
        short_buyback=short_buyback,
    )


def _state_for_unlinked_call(call, *, as_of: date, underlying_price: Decimal | None) -> PMCCState:
    short_premium = _money((call.entry_price or ZERO) * call.quantity * call.multiplier)
    short_buyback = _money((call.current_price or ZERO) * call.quantity * call.multiplier)
    return _compose_state(
        symbol=call.symbol,
        long_position_id=None,
        short_calls=[call],
        long_quantity=ZERO,
        short_quantity=call.quantity,
        covered_contracts=ZERO,
        long_debit=ZERO,
        long_current_value=ZERO,
        long_expiration=None,
        as_of=as_of,
        underlying_price=underlying_price,
        short_premium=short_premium,
        short_buyback=short_buyback,
    )


def _compose_state(
    *,
    symbol: str,
    long_position_id: int | None,
    short_calls: list,
    long_quantity: Decimal,
    short_quantity: Decimal,
    covered_contracts: Decimal,
    long_debit: Decimal,
    long_current_value: Decimal,
    long_expiration: date | None,
    as_of: date,
    underlying_price: Decimal | None,
    short_premium: Decimal,
    short_buyback: Decimal,
) -> PMCCState:
    short_expiration = min(
        (call.expiration for call in short_calls if call.expiration is not None),
        default=None,
    )
    strikes = [call.strike for call in short_calls if call.strike is not None]
    # When several short calls are linked to one long leg, the lowest strike
    # is the first one that can create assignment risk.
    short_strike = min(strikes) if strikes else None
    long_dte = _dte(long_expiration, as_of)
    short_dte = _dte(short_expiration, as_of)
    expired = (
        long_dte is not None
        and long_dte <= 0
    ) or (short_dte is not None and short_dte <= 0)
    uncovered = long_position_id is None or not short_calls or short_quantity > covered_contracts
    assignment_risk = bool(
        short_calls
        and underlying_price is not None
        and short_strike is not None
        and underlying_price >= short_strike
    )
    needs_roll = bool(
        short_calls
        and not expired
        and ((short_dte is not None and short_dte <= SHORT_CALL_ROLL_DTE) or (long_dte is not None and long_dte <= LONG_LEAPS_ROLL_DTE))
    )
    if expired:
        status, reason = "expired", "Long LEAPS 或 Short Call 已到期"
    elif uncovered:
        status, reason = "uncovered", "缺少有效的 Long LEAPS 覆盖，或 Short Call 数量超过覆盖量"
    elif assignment_risk:
        status, reason = "assignment_risk", "标的价格已达到 Short Call 行权价，需评估提前行权与展期"
    elif needs_roll:
        status, reason = "needs_roll", "Long LEAPS 或 Short Call 剩余期限进入展期窗口"
    else:
        status, reason = "covered", "Short Call 数量不超过 Long LEAPS 覆盖量"
    ratio = short_quantity / covered_contracts if covered_contracts > ZERO else ZERO
    short_current_value = short_buyback
    return PMCCState(
        symbol=symbol,
        long_position_id=long_position_id,
        short_call_ids=tuple(call.id for call in short_calls),
        status=status,
        reason=reason,
        long_quantity=long_quantity,
        short_quantity=short_quantity,
        covered_contracts=covered_contracts,
        coverage_ratio=ratio.quantize(Decimal("0.0001")),
        long_debit=long_debit,
        short_premium_received=short_premium,
        short_buyback_cost=short_buyback,
        short_call_pnl=(short_premium - short_buyback).quantize(CENT),
        net_cash_flow=(short_premium - short_buyback).quantize(CENT),
        net_debit=max(long_debit - short_premium, ZERO).quantize(CENT),
        maximum_loss=long_debit.quantize(CENT),
        long_current_value=long_current_value,
        short_current_value=short_current_value,
        current_exposure=(long_current_value - short_current_value).quantize(CENT),
        long_expiration=long_expiration,
        short_expiration=short_expiration,
        long_dte=long_dte,
        short_dte=short_dte,
        short_strike=short_strike,
        underlying_price=underlying_price,
        assignment_risk=assignment_risk,
        needs_roll=needs_roll,
    )


def _dte(expiration: date | None, as_of: date) -> int | None:
    return (expiration - as_of).days if expiration is not None else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)
