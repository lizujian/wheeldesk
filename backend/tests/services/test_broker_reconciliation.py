from datetime import date
from decimal import Decimal

from ib_async import Stock, Option
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import Base, UnmanagedPositionRecord
from app.services.broker_reconciliation import reconcile_positions


def test_current_holdings_reconcile_without_importing_or_overwriting_trades():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    class Broker:
        def call(self, method):
            assert method == "positions"
            return [{"contract": Stock("BRK B", "SMART", "USD"), "quantity": 2},
                {"contract": Option("AVGO", "20261106", 390, "C", "SMART", multiplier="100", currency="USD"), "quantity": -1},
                {"contract": Stock("QQQ", "SMART", "USD"), "quantity": 3}]
    with Session(engine) as session:
        session.add_all([
            UnmanagedPositionRecord(category="other", symbol="BRK.B", asset_type="equity", direction="long", quantity=1, multiplier=1, current_price=500),
            UnmanagedPositionRecord(category="other", symbol="BRK.B", asset_type="equity", direction="long", quantity=1, multiplier=1, current_price=500),
            UnmanagedPositionRecord(category="other", symbol="AVGO", asset_type="option", option_type="call", direction="short", quantity=1, multiplier=100, current_price=5, expiration=date(2026,11,6), strike=390),
        ])
        session.commit()
        before = [(r.id, r.quantity, r.current_price) for r in session.scalars(select(UnmanagedPositionRecord))]
        result = reconcile_positions(session, Broker())
        assert result["matched_count"] == 2 and not result["ledger_updated"]
        assert len(result["differences"]) == 1
        assert result["differences"][0]["symbol"] == "QQQ"
        assert result["differences"][0]["ledger_quantity"] == 0
        assert result["differences"][0]["broker_quantity"] == 3
        assert [(r.id,r.quantity,r.current_price) for r in session.scalars(select(UnmanagedPositionRecord))] == before
    engine.dispose()
