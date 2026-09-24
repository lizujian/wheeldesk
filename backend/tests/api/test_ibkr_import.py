from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.db_models import Base
from app.main import app
from app.services.ibkr_import import parse_activity_statement


REPORT = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"August 1, 2026 - August 26, 2026"
Trades,Header,Asset Category,Currency,Symbol,Underlying Symbol,Date/Time,Quantity,T. Price,C. Price,Expiry,Strike,Put/Call,Code
Trades,Data,Stocks,USD,BRK B,,2026-08-05 10:30:00,10,500,510,,,,O
Trades,Data,Equity and Index Options,USD,QQQ  270820C00500000,QQQ,2026-08-18 11:00:00,1,100,105,2027-08-20,500,C,O
Trades,Data,Equity and Index Options,USD,TQQQ  261002P00055000,TQQQ,2026-08-24 12:00:00,-2,1.5,1.1,2026-10-02,55,P,O
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Underlying Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Stocks,USD,BRK B,,10,1,500,5000,510,5100,100,,,,
Open Positions,Data,Summary,Stocks,USD,AAPL,,5,1,220,1100,230,1150,50,,,,
Open Positions,Data,Summary,Equity and Index Options,USD,QQQ  270820C00500000,QQQ,1,100,100,10000,105,10500,500,2027-08-20,500,C,
Open Positions,Data,Summary,Equity and Index Options,USD,TQQQ  261002P00055000,TQQQ,-2,100,1.5,-300,1.1,-220,80,2026-10-02,55,P,
Deposits & Withdrawals,Header,Currency,Settle Date,Description,Amount
Deposits & Withdrawals,Data,USD,2026-08-12,Electronic Fund Transfer,25000
'''


LOCALIZED_REPORT = '''Statement,Header,域名称,域值
Statement,Data,Period,"一月 1, 2026 - 八月 25, 2026"
未平仓持仓,Header,DataDiscriminator,资产分类,货币,代码,开盘,数量,合约乘数,成本价格,成本基础,收盘价格,价值,未实现的损益,代码
未平仓持仓,Data,Summary,股票,USD,BOXX,-,100,1,99.5,9950,100,10000,50,
未平仓持仓,Data,Lot,股票,USD,BOXX,2026-08-01,100,1,99.5,9950,100,10000,50,
未平仓持仓,Data,Summary,股票和指数期权,USD,AAPL  270115C00200000,-,-1,100,12,-1200,15,-1500,-300,
未平仓持仓,Data,Summary,股票和指数期权,USD,GOOG  270115C00150000,-,1,100,29.99,2999,35,3500,501,
交易,Header,DataDiscriminator,资产分类,货币,代码,日期/时间,数量,交易价格,收盘价格,收益,佣金/税,基础,已实现的损益,按市值计算的损益,代码
交易,Data,Order,股票和指数期权,USD,GOOG  270115C00150000,"2026-08-10, 10:30:00",1,30,35,-3000,0,3000,0,500,O
存款和取款,Header,货币,结算日期,描述,金额
存款和取款,Data,USD,2026-08-03,电子资金转账,1000
存款和取款,Data,USD,,,1000
'''

LOCALIZED_NAV_REPORT = LOCALIZED_REPORT + '''净资产值变更,Header,域名称,域值
净资产值变更,Data,开始价值,50000
净资产值变更,Data,存款和取款,1000
净资产值变更,Data,结束价值,60000
'''

SINGLE_DAY_REPORT = '''Statement,Header,域名称,域值
Statement,Data,Period,"八月 25, 2026"
未平仓持仓,Header,DataDiscriminator,资产分类,货币,代码,开盘,数量,合约乘数,成本价格,成本基础,收盘价格,价值,未实现的损益,代码
未平仓持仓,Data,Summary,股票,USD,BOXX,-,100,1,99.5,9950,100,10000,50,
'''

AVGO_INITIAL_REPORT = '''Statement,Header,域名称,域值
Statement,Data,Period,"八月 25, 2026"
交易,Header,DataDiscriminator,资产分类,货币,代码,日期/时间,数量,交易价格,收盘价格,收益,佣金/税,基础,已实现的损益,按市值计算的损益,代码
交易,Data,Order,股票和指数期权,USD,AAPL 28AUG26 250 P,"2026-08-14, 10:00:00",-1,4,10,400,0,-400,0,-600,O
未平仓持仓,Header,DataDiscriminator,资产分类,货币,代码,开盘,数量,合约乘数,成本价格,成本基础,收盘价格,价值,未实现的损益,代码
未平仓持仓,Data,Summary,股票和指数期权,USD,AAPL 28AUG26 250 P,-,-1,100,4,-400,10,-1000,-600,
'''

AVGO_ROLL_REPORT = '''Statement,Header,域名称,域值
Statement,Data,Period,"八月 26, 2026"
未平仓持仓,Header,DataDiscriminator,资产分类,货币,代码,数量,合约乘数,成本价格,成本基础,收盘价格,价值,未实现的损益,代码
未平仓持仓,Data,Summary,股票和指数期权,USD,AAPL 25SEP26 250 P,-1,100,12,-1200,11,-1100,100,
交易,Header,DataDiscriminator,资产分类,货币,代码,日期/时间,数量,交易价格,收盘价格,收益,佣金/税,基础,已实现的损益,按市值计算的损益,代码
交易,Data,Order,股票和指数期权,USD,AAPL 28AUG26 250 P,"2026-08-26, 11:00:00",1,10,10,-1000,0,400,-600,0,C
交易,Data,Order,股票和指数期权,USD,AAPL 25SEP26 250 P,"2026-08-26, 11:00:00",-1,12,11,1200,0,-1200,0,100,O
'''

CLOSING_TRADE_INITIAL_REPORT = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"August 25, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L
Open Positions,Data,Summary,Equity and Index Options,USD,TQQQ 02OCT26 55 P,-2,100,1.5,-300,1,-200,100
Open Positions,Data,Summary,Equity and Index Options,USD,AAPL 04SEP26 250 P,-1,100,5,-500,3,-300,200
Open Positions,Data,Summary,Equity and Index Options,USD,GOOG 19MAR27 180 C,1,100,20,2000,25,2500,500
Open Positions,Data,Summary,Equity and Index Options,USD,IBM 28AUG26 200 C,-2,100,1,-200,0.5,-100,100
'''

CLOSING_TRADES_REPORT = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"August 26, 2026"
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Equity and Index Options,USD,AAPL 04SEP26 250 P,"2026-08-26, 11:00:00",1,3,3,-300,0,500,200,0,C
Trades,Data,Order,Equity and Index Options,USD,GOOG 19MAR27 180 C,"2026-08-26, 11:05:00",-1,25,25,2500,0,-2000,500,0,C
Trades,Data,Order,Equity and Index Options,USD,INTC 11SEP26 40 C,"2026-08-26, 09:30:00",-2,2,1.75,400,0,-400,0,50,O
Trades,Data,Order,Equity and Index Options,USD,INTC 11SEP26 40 C,"2026-08-26, 10:30:00",2,1.5,1.75,-300,0,400,100,50,C
Trades,Data,Order,Equity and Index Options,USD,IBM 28AUG26 200 C,"2026-08-26, 12:30:00",2,0.5,0.5,-100,0,200,100,0,C
Trades,Data,Order,Equity and Index Options,USD,TQQQ 02OCT26 55 P,"2026-08-26, 09:45:00",2,1,1,-200,0,300,100,0,C
'''

MSFT_CALL_ROLL_REPORT = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"August 28, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L
Open Positions,Data,Summary,Equity and Index Options,USD,MSFT 18JUN27 390 C,2,100,47.5,9500,49,9800,300
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Equity and Index Options,USD,MSFT 18DEC26 400 C,"2026-08-28, 10:00:00",-2,45,45,9000,0,-10000,-1000,0,C
Trades,Data,Order,Equity and Index Options,USD,MSFT 18JUN27 390 C,"2026-08-28, 10:00:45",2,47.5,49,-9500,0,9500,0,300,O
'''


@contextmanager
def import_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    sessions = sessionmaker(engine, expire_on_commit=False, class_=Session)
    Base.metadata.create_all(engine)

    def override_session():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        initialized = client.post(
            "/api/portfolio/initialize",
            json={"age": 36, "opening_equity": 100000, "opening_date": "2026-08-01"},
        )
        assert initialized.status_code == 201
        yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_ibkr_activity_statement_previews_matches_and_confirms_selected_rows() -> None:
    with import_client() as client:
        preview_response = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "activity.csv", "content": REPORT},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["recognized_sections"] == [
            "Deposits & Withdrawals",
            "Open Positions",
            "Trades",
        ]
        assert preview["summary"] == {
            "ready": 5,
            "matched": 0,
            "review": 0,
            "unsupported": 0,
            "duplicate": 0,
            "selected": 5,
        }

        put = next(row for row in preview["rows"] if row["instrument"].endswith("Put"))
        assert put["status"] == "ready"
        assert put["can_import"] is True
        selected = [row["fingerprint"] for row in preview["rows"]]
        confirmed = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "activity.csv",
                "content": REPORT,
                "selected_fingerprints": selected,
                "overrides": {
                    put["fingerprint"]: {"underlying_entry_price": 68.1}
                },
                "confirmation": "IMPORT",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["imported"] == 5

        positions = client.get("/api/positions").json()
        assert {(row["symbol"], row["quantity"]) for row in positions} == {
            ("BRK.B", 10.0),
            ("QQQ", 1.0),
        }
        assert next(row for row in positions if row["symbol"] == "QQQ")["opened_on"] == "2026-08-18"
        others = client.get("/api/other-holdings").json()
        assert others["records"][0]["symbol"] == "AAPL"
        assert others["records"][0]["current_value"] == 1150.0
        wheel = client.get("/api/wheel/overview").json()
        assert wheel["capital"]["put_collateral"] == 11000.0
        portfolio = client.get("/api/portfolio/summary").json()
        assert portfolio["net_external_capital"] == 125000.0
        assert portfolio["balances"]["cash"] == 30000.0
        assert len(client.get("/api/imports/ibkr/history").json()) == 5


def test_ibkr_import_classifies_voo_as_core_equity() -> None:
    report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"August 28, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Underlying Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Stocks,USD,VOO,,12.5,1,590,7375,600,7500,125,,,,
'''
    with import_client() as client:
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "voo.csv", "content": report},
        ).json()
        voo = next(row for row in preview["rows"] if row["instrument"] == "VOO")

        assert voo["action"] == "create_position"
        assert voo["details"]["bucket"] == "core"
        confirmed = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "voo.csv",
                "content": report,
                "selected_fingerprints": [voo["fingerprint"]],
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        position = client.get("/api/positions").json()[0]
        assert position["symbol"] == "VOO"
        assert position["bucket"] == "core"


def test_ibkr_import_classifies_schd_as_core_equity() -> None:
    report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"August 28, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Underlying Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Stocks,USD,SCHD,,10,1,32,320,33,330,10,,,,
'''
    with import_client() as client:
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "schd.csv", "content": report},
        ).json()

        schd = next(row for row in preview["rows"] if row["instrument"] == "SCHD")
        assert schd["action"] == "create_position"
        assert schd["details"]["bucket"] == "core"


def test_ibkr_import_classifies_brk_puts_as_core_accumulation() -> None:
    from app.api.market import get_market_provider, get_option_provider
    from app.market.base import MarketDataError
    from app.market.sample import SampleMarketDataProvider

    class CoreProvider(SampleMarketDataProvider):
        def option_quote(self, *args, **kwargs):
            raise MarketDataError("No option quote in this test")

    report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"September 4, 2026"
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Equity and Index Options,USD,BRK B 18SEP26 500 P,"2026-09-04, 12:54:47",-1,2.75,2.64,275,0,-275,0,11,O
Trades,Data,Order,Equity and Index Options,USD,BRK B 02OCT26 500 P,"2026-09-04, 15:53:42",-1,4.65,4.55,465,0,-465,0,10,O
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L
Open Positions,Data,Summary,Equity and Index Options,USD,BRK B 18SEP26 500 P,-1,100,2.75,-275,2.64,-264,11
Open Positions,Data,Summary,Equity and Index Options,USD,BRK B 02OCT26 500 P,-1,100,4.65,-465,4.55,-455,10
'''
    with import_client() as client:
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "brk-core-puts.csv", "content": report},
        ).json()

        puts = [row for row in preview["rows"] if row["action"] == "create_wheel_put"]
        assert len(puts) == 2
        assert all(row["status"] == "ready" for row in puts)
        assert all(row["details"]["capital_bucket"] == "core" for row in puts)

        imported = client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "brk-core-puts.csv", "content": report},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["imported"] == 2
        assert imported.json()["needs_attention"] == 0

        wheel = client.get("/api/wheel/overview").json()
        assert wheel["rounds"] == []
        assert wheel["capital"]["put_collateral"] == 0.0
        assert len(wheel["core_puts"]) == 2
        assert {row["expiration"] for row in wheel["core_puts"]} == {
            "2026-09-18",
            "2026-10-02",
        }
        assert sum(row["collateral"] for row in wheel["core_puts"]) == 100000.0

        portfolio = client.get("/api/portfolio/summary").json()
        assert portfolio["capital"]["core"]["committed"] == 100000.0
        assert portfolio["capital"]["core"]["cash_occupancy"] == 30000.0
        assert portfolio["capital"]["wheel"]["committed"] == 0.0
        assert portfolio["capital"]["cash"]["occupied"] == 30000.0
        assert portfolio["capital"]["cash"]["margin_shortfall"] == 25000.0

        provider = CoreProvider()
        app.dependency_overrides[get_market_provider] = lambda: provider
        app.dependency_overrides[get_option_provider] = lambda: provider
        refreshed = client.post("/api/market/refresh")
        assert refreshed.status_code == 200, refreshed.text
        core = refreshed.json()["core"]
        assert core["pending_put_collateral"] == 100000.0
        assert core["unplanned_gap"] == 0
        assert core["total_value"] == 0
        assert core["mode"] == "accumulating"
        assert not core["recommendation"]["actionable"]
        assert core["sell_put"]["code"] == "pending_puts"
        assert not core["sell_put"]["actionable"]


def test_ibkr_import_classifies_spy_put_as_core_acquisition() -> None:
    report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"September 14, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Equity and Index Options,USD,SPY 02OCT26 735 P,-1,100,3.69,-369,3.11,-311,58,2026-10-02,735,P,
'''
    with import_client() as client:
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "spy-core-put.csv", "content": report},
        ).json()
        put = preview["rows"][0]
        assert put["action"] == "create_wheel_put"
        assert put["details"]["capital_bucket"] == "core"
        assert "核心仓 Sell Put 建仓" in put["message"]

        imported = client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "spy-core-put.csv", "content": report},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["needs_attention"] == 0
        wheel = client.get("/api/wheel/overview").json()
        assert wheel["core_puts"][0]["symbol"] == "SPY"
        assert client.get("/api/other-holdings").json()["records"] == []


def test_ibkr_import_classifies_and_closes_leaps_sell_call() -> None:
    long_report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"August 31, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Equity and Index Options,USD,GOOG 19MAR27 330 C,1,100,38.86,3886,36.88,3688,-198,2027-03-19,330,C,
'''
    short_report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"September 14, 2026"
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Equity and Index Options,USD,GOOG 02OCT26 360 C,"2026-09-14, 10:30:00",-1,3.5,3.5,350,0,-350,0,0,O
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Equity and Index Options,USD,GOOG 02OCT26 360 C,-1,100,3.5,-350,3.975,-397.5,-47.5,2026-10-02,360,C,
'''
    close_report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"September 15, 2026"
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Equity and Index Options,USD,GOOG 02OCT26 360 C,"2026-09-15, 10:30:00",1,2.0,2.0,-200,0,350,150,0,C
'''
    with import_client() as client:
        assert client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "goog-long.csv", "content": long_report},
        ).status_code == 200
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "goog-short.csv", "content": short_report},
        ).json()
        short_call = next(row for row in preview["rows"] if row["action"] == "create_leaps_call")
        assert short_call["details"]["linked_position_id"] is not None
        assert "PMCC Short Call" in short_call["message"]

        imported = client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "goog-short.csv", "content": short_report},
        )
        assert imported.status_code == 200, imported.text
        listing = client.get("/api/other-holdings?include_closed=true").json()
        assert listing["records"] == []
        assert listing["leaps_call_wheels"][0]["category"] == "leaps_call_wheel"

        closed = client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "goog-close.csv", "content": close_report},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["needs_attention"] == 0
        listing = client.get("/api/other-holdings?include_closed=true").json()
        call = listing["leaps_call_wheels"][0]
        assert call["status"] == "closed"
        assert call["realized_profit"] == 150.0
        assert client.get("/api/profit-ledger").json()["summary"]["leaps_realized"] == 150.0


def test_ibkr_import_links_short_call_when_multiple_leaps_can_cover_it() -> None:
    short_report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"September 14, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Equity and Index Options,USD,AVGO 23OCT26 400 C,-1,100,5.05,-505,5.25,-525,-20,2026-10-23,400,C,
'''
    with import_client() as client:
        long_ids = []
        for opened_on, expiration, strike in (
            ("2026-08-01", "2027-02-19", 360),
            ("2026-09-01", "2027-09-17", 330),
        ):
            response = client.post(
                "/api/positions",
                json={
                    "bucket": "leaps",
                    "symbol": "AVGO",
                    "asset_type": "option",
                    "direction": "long",
                    "option_type": "call",
                    "quantity": 1,
                    "entry_price": 100,
                    "opened_on": opened_on,
                    "expiration": expiration,
                    "strike": strike,
                    "tranche": len(long_ids) + 1,
                },
            )
            assert response.status_code == 201, response.text
            long_ids.append(response.json()["id"])

        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "avgo-short.csv", "content": short_report},
        ).json()
        short_call = preview["rows"][0]
        assert short_call["action"] == "create_leaps_call"
        assert short_call["details"]["linked_position_id"] == long_ids[0]

        imported = client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "avgo-short.csv", "content": short_report},
        )
        assert imported.status_code == 200, imported.text
        listing = client.get("/api/other-holdings?include_closed=true").json()
        call = listing["leaps_call_wheels"][0]
        assert call["category"] == "leaps_call_wheel"
        assert call["linked_position_id"] == long_ids[0]
        state = next(
            state
            for state in listing["pmcc"]["states"]
            if state["long_position_id"] == long_ids[0]
        )
        assert state["status"] == "covered"


def test_ibkr_import_classifies_qld_sell_call_as_leaps_wheel() -> None:
    qld_report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"July 29, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Stocks,USD,QLD,100,1,79.36,7936,89.55,8955,1019,,,,
'''
    call_report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"September 4, 2026"
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Equity and Index Options,USD,QLD 18SEP26 90 C,"2026-09-04, 10:30:00",-1,2.12,2.12,212,0,-212,0,0,O
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Equity and Index Options,USD,QLD 18SEP26 90 C,-1,100,2.12,-212,2.64,-264,-52,2026-09-18,90,C,
'''
    with import_client() as client:
        qld = client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "qld-stock.csv", "content": qld_report},
        )
        assert qld.status_code == 200, qld.text

        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "qld-call.csv", "content": call_report},
        ).json()
        call = next(row for row in preview["rows"] if row["action"] == "create_leaps_call")
        assert call["details"]["linked_position_id"] is not None
        assert "PMCC Short Call" in call["message"]

        imported = client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "qld-call.csv", "content": call_report},
        )
        assert imported.status_code == 200, imported.text
        listing = client.get("/api/other-holdings?include_closed=true").json()
        assert listing["records"] == []
        assert listing["leaps_call_wheels"][0]["symbol"] == "QLD"
        assert listing["leaps_call_wheels"][0]["linked_position_id"] is not None


def test_localized_statement_normalizes_headers_and_skips_aggregate_rows() -> None:
    with import_client() as client:
        preview_response = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "localized.csv", "content": LOCALIZED_REPORT},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()

        assert preview["report_as_of"] == "2026-08-25"
        assert preview["recognized_sections"] == [
            "Deposits & Withdrawals",
            "Open Positions",
            "Trades",
        ]
        assert preview["summary"] == {
            "ready": 4,
            "matched": 0,
            "review": 0,
            "unsupported": 0,
            "duplicate": 0,
            "selected": 4,
        }
        assert len(preview["rows"]) == 4
        assert {row["instrument"] for row in preview["rows"]} == {
            "BOXX",
            "AAPL 2027-01-15 $200 Call",
            "GOOG 2027-01-15 $150 Call",
            "电子资金转账",
        }
        assert all(row["source"].get("DataDiscriminator") != "Lot" for row in preview["rows"])

        selected = [row["fingerprint"] for row in preview["rows"] if row["selected"]]
        confirmed = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "localized.csv",
                "content": LOCALIZED_REPORT,
                "selected_fingerprints": selected,
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["imported"] == 4

        other = client.get("/api/other-holdings").json()
        assert other["cash_equivalent_value"] == 10000
        boxx = next(row for row in other["records"] if row["symbol"] == "BOXX")
        assert boxx["opened_on"] == "2026-08-25"
        short_call = next(
            row for row in other["records"] if row["symbol"] == "AAPL"
        )
        assert short_call["direction"] == "short"
        assert short_call["option_type"] == "call"

        leaps = next(
            row for row in client.get("/api/positions").json() if row["symbol"] == "GOOG"
        )
        assert leaps["opened_on"] == "2026-08-10"
        assert leaps["entry_price"] == 30
        assert leaps["underlying_entry_price"] is None
        assert client.get("/api/portfolio/summary").json()["net_external_capital"] == 101000

        repeated = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "localized-again.csv", "content": LOCALIZED_REPORT},
        ).json()
        assert repeated["summary"]["duplicate"] == 4
        assert repeated["summary"]["selected"] == 0


def test_single_day_statement_uses_its_period_as_report_date() -> None:
    with import_client() as client:
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "single-day.csv", "content": SINGLE_DAY_REPORT},
        ).json()

        assert preview["report_as_of"] == "2026-08-25"
        assert preview["rows"][0]["details"]["opened_on"] == "2026-08-25"


def test_single_day_statement_imports_sell_put_roll_as_one_idempotent_action() -> None:
    with import_client() as client:
        initial = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "avgo-20260825.csv", "content": AVGO_INITIAL_REPORT},
        ).json()
        old_put = initial["rows"][0]
        created = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "avgo-20260825.csv",
                "content": AVGO_INITIAL_REPORT,
                "selected_fingerprints": [old_put["fingerprint"]],
                "overrides": {
                    old_put["fingerprint"]: {
                        "underlying_entry_price": 245,
                        "earnings_confirmed": True,
                    }
                },
                "confirmation": "IMPORT",
            },
        )
        assert created.status_code == 200, created.text

        preview_response = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "avgo-20260826.csv", "content": AVGO_ROLL_REPORT},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["summary"] == {
            "ready": 1,
            "matched": 0,
            "review": 0,
            "unsupported": 0,
            "duplicate": 0,
            "selected": 1,
        }
        roll = preview["rows"][0]
        assert roll["action"] == "roll_wheel_put"
        assert roll["instrument"] == "AAPL Sell Put 展期"
        assert roll["details"]["old_expiration"] == "2026-08-28"
        assert roll["details"]["expiration"] == "2026-09-25"
        assert roll["details"]["buyback_premium"] == 10
        assert roll["details"]["new_premium"] == 12
        assert roll["details"]["net_credit"] == 200.0

        confirmed = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "avgo-20260826.csv",
                "content": AVGO_ROLL_REPORT,
                "selected_fingerprints": [roll["fingerprint"]],
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["results"][0]["action"] == "roll_wheel_put"

        overview = client.get("/api/wheel/overview").json()
        avgo = [put for round_record in overview["rounds"] for put in round_record["puts"]]
        assert len(avgo) == 2
        old, current = avgo
        assert old["state"] == "rolled"
        assert old["close_premium"] == 10
        assert old["realized_profit"] == -600.0
        assert old["rolled_to"]["to_put_id"] == current["id"]
        assert current["state"] == "open"
        assert current["round_id"] == old["round_id"]
        assert current["premium"] == 12
        assert current["collateral"] == 25000.0
        assert current["roll_count"] == 1
        assert current["rolled_from"]["net_credit"] == 200.0
        assert current["rolled_from"]["previous_realized_profit"] == -600.0
        assert overview["capital"]["put_collateral"] == 25000.0

        repeated = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "avgo-again.csv", "content": AVGO_ROLL_REPORT},
        ).json()
        assert repeated["summary"]["duplicate"] == 1
        assert repeated["summary"]["selected"] == 0

        interval_report = AVGO_ROLL_REPORT.replace(
            '"八月 26, 2026"',
            '"八月 26, 2026 - 八月 31, 2026"',
        )
        interval = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "avgo-august.csv", "content": interval_report},
        ).json()
        assert interval["summary"]["duplicate"] == 1
        assert interval["summary"]["selected"] == 0


def test_trade_rows_close_strategy_and_other_positions_and_record_intraday_round_trip() -> None:
    with import_client() as client:
        initial = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "initial.csv", "content": CLOSING_TRADE_INITIAL_REPORT},
        ).json()
        seeded = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "initial.csv",
                "content": CLOSING_TRADE_INITIAL_REPORT,
                "selected_fingerprints": [row["fingerprint"] for row in initial["rows"] if row["selected"]],
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert seeded.status_code == 200, seeded.text

        preview_response = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "closing.csv", "content": CLOSING_TRADES_REPORT},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        actions = {row["instrument"]: row["action"] for row in preview["rows"]}
        assert actions == {
            "AAPL 2026-09-04 $250 Put": "close_wheel_put",
            "GOOG 2027-03-19 $180 Call": "close_position",
            "INTC 2026-09-11 $40 Call": "record_closed_unmanaged",
            "IBM 2026-08-28 $200 Call": "close_unmanaged",
            "TQQQ 2026-10-02 $55 Put": "close_wheel_put",
        }
        assert preview["summary"]["ready"] == 5
        assert preview["summary"]["selected"] == 5

        confirmed = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "closing.csv",
                "content": CLOSING_TRADES_REPORT,
                "selected_fingerprints": [row["fingerprint"] for row in preview["rows"]],
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert confirmed.status_code == 200, confirmed.text

        wheel = client.get("/api/wheel/overview").json()
        wheel_puts = [put for round_record in wheel["rounds"] for put in round_record["puts"]]
        assert {(put["symbol"], put["state"]) for put in wheel_puts} == {
            ("AAPL", "closed"),
            ("TQQQ", "closed"),
        }
        positions = client.get("/api/positions?include_closed=true").json()
        goog_call = next(row for row in positions if row["symbol"] == "GOOG")
        assert goog_call["status"] == "closed"
        assert goog_call["realized_profit"] == 500.0
        others = client.get("/api/other-holdings?include_closed=true").json()["records"]
        ibm = next(row for row in others if row["symbol"] == "IBM")
        intc = next(row for row in others if row["symbol"] == "INTC")
        assert ibm["status"] == "closed"
        assert intc["status"] == "closed"
        assert intc["realized_profit"] == 100.0

        repeated = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "closing-again.csv", "content": CLOSING_TRADES_REPORT},
        ).json()
        assert repeated["summary"]["duplicate"] == 5
        assert repeated["summary"]["selected"] == 0


def test_auto_import_links_two_contract_leaps_roll_and_is_idempotent() -> None:
    with import_client() as client:
        opened = client.post(
            "/api/positions",
            json={
                "bucket": "leaps",
                "symbol": "MSFT",
                "asset_type": "option",
                "direction": "long",
                "option_type": "call",
                "quantity": 2,
                "entry_price": 50,
                "opened_on": "2026-08-20",
                "expiration": "2026-12-18",
                "strike": 400,
                "tranche": 1,
            },
        )
        assert opened.status_code == 201, opened.text
        previous_id = opened.json()["id"]

        imported = client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "synthetic-roll.csv", "content": MSFT_CALL_ROLL_REPORT},
        )
        assert imported.status_code == 200, imported.text
        payload = imported.json()
        assert payload["imported"] == 1
        assert payload["needs_attention"] == 0
        assert payload["results"][0]["action"] == "roll_position"

        positions = client.get("/api/positions?include_closed=true").json()
        previous = next(row for row in positions if row["id"] == previous_id)
        current = next(row for row in positions if row["status"] == "open")
        assert previous["status"] == "closed"
        assert previous["realized_profit"] == -1000
        assert current["quantity"] == 2
        assert current["entry_price"] == 47.5
        assert current["expiration"] == "2027-06-18"
        assert current["strike"] == 390
        assert current["tranche"] == 1
        assert current["rolled_from_position_id"] == previous_id

        repeated = client.post(
            "/api/imports/ibkr/auto",
            json={"filename": "synthetic-roll-again.csv", "content": MSFT_CALL_ROLL_REPORT},
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["imported"] == 0
        assert repeated.json()["unchanged"] == 1
        assert repeated.json()["needs_attention"] == 0


def test_first_annual_statement_replaces_manual_baseline_and_reconciles_nav() -> None:
    with import_client() as client:
        manual = client.post(
            "/api/portfolio/deposits",
            json={"amount": 25000, "date": "2026-08-01", "note": "测试入金"},
        )
        assert manual.status_code == 200
        assert manual.json()["total_equity"] == 125000

        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "annual-localized.csv", "content": LOCALIZED_NAV_REPORT},
        ).json()
        assert preview["account_summary"] == {
            "period_start": "2026-01-01",
            "period_end": "2026-08-25",
            "starting_value": 50000,
            "deposits_withdrawals": 1000,
            "ending_value": 60000,
        }

        selected = [row["fingerprint"] for row in preview["rows"] if row["selected"]]
        confirmed = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "annual-localized.csv",
                "content": LOCALIZED_NAV_REPORT,
                "selected_fingerprints": selected,
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert confirmed.status_code == 200, confirmed.text

        portfolio = client.get("/api/portfolio/summary").json()
        assert portfolio["total_equity"] == 60000
        assert portfolio["net_external_capital"] == 51000
        assert portfolio["investment_profit"] == 9000

        deposits = [
            row for row in client.get("/api/ledger/events").json()
            if row["event_type"] == "deposit"
        ]
        assert [(row["occurred_on"], row["amount"]) for row in deposits] == [
            ("2026-08-03", 1000)
        ]

        repeated = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "annual-again.csv", "content": LOCALIZED_NAV_REPORT},
        ).json()
        assert repeated["summary"]["duplicate"] == 4
        assert client.get("/api/portfolio/summary").json()["total_equity"] == 60000


def test_reimport_matches_prices_at_database_precision() -> None:
    report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"January 1, 2026 - August 25, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Underlying Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Stocks,USD,BOXX,,10,1,99.512345,995.12345,100.123456,1001.23456,6.11111,,,,
'''
    with import_client() as client:
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "precision.csv", "content": report},
        ).json()
        selected = [row["fingerprint"] for row in preview["rows"] if row["selected"]]
        confirmed = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "precision.csv",
                "content": report,
                "selected_fingerprints": selected,
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert confirmed.status_code == 200, confirmed.text

        repeated = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "precision-again.csv", "content": report},
        ).json()
        assert repeated["summary"]["duplicate"] == 1
        assert repeated["summary"]["selected"] == 0


def test_reimport_stays_duplicate_after_live_quote_changes() -> None:
    with import_client() as client:
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "localized.csv", "content": LOCALIZED_REPORT},
        ).json()
        selected = [row["fingerprint"] for row in preview["rows"] if row["selected"]]
        confirmed = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "localized.csv",
                "content": LOCALIZED_REPORT,
                "selected_fingerprints": selected,
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert confirmed.status_code == 200, confirmed.text

        boxx = next(
            row
            for row in client.get("/api/other-holdings").json()["records"]
            if row["symbol"] == "BOXX"
        )
        marked = client.patch(
            f"/api/other-holdings/{boxx['id']}",
            json={"current_price": 101},
        )
        assert marked.status_code == 200, marked.text

        repeated = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "localized-again.csv", "content": LOCALIZED_REPORT},
        ).json()
        assert repeated["summary"]["duplicate"] == 4
        assert repeated["summary"]["ready"] == 0
        assert repeated["summary"]["selected"] == 0


def test_ibkr_import_is_idempotent_even_when_report_is_renamed() -> None:
    with import_client() as client:
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "first.csv", "content": REPORT},
        ).json()
        ready = [row for row in preview["rows"] if row["selected"]]
        response = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "first.csv",
                "content": REPORT,
                "selected_fingerprints": [row["fingerprint"] for row in ready],
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert response.status_code == 200, response.text

        repeated = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "renamed.csv", "content": REPORT},
        ).json()
        duplicate_symbols = {
            row["instrument"] for row in repeated["rows"] if row["status"] == "duplicate"
        }
        assert {"BRK.B", "AAPL", "QQQ 2027-08-20 $500 Call", "Electronic Fund Transfer"} <= duplicate_symbols
        assert repeated["summary"]["selected"] == 0


def test_ibkr_import_rejects_non_statement_csv() -> None:
    with import_client() as client:
        response = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "positions.csv", "content": "symbol,quantity\nQQQ,1\n"},
        )
        assert response.status_code == 422
        assert "未识别" in response.text


def test_ibkr_preview_matches_aggregated_contract_without_overwriting_lots() -> None:
    with import_client() as client:
        position_ids = []
        for tranche, entry_price in ((1, 100), (2, 120)):
            opened = client.post(
                "/api/positions",
                json={
                    "bucket": "leaps",
                    "symbol": "QQQ",
                    "asset_type": "option",
                    "direction": "long",
                    "option_type": "call",
                    "quantity": 1,
                    "entry_price": entry_price,
                    "opened_on": "2026-08-18",
                    "expiration": "2027-08-20",
                    "strike": 500,
                    "tranche": tranche,
                },
            )
            assert opened.status_code == 201, opened.text
            position_ids.append(opened.json()["id"])
        for position_id in position_ids:
            client.patch(f"/api/positions/{position_id}/mark", json={"price": 115})

        report = '''Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Underlying Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Equity and Index Options,USD,QQQ  270820C00500000,QQQ,2,100,110,22000,115,23000,1000,2027-08-20,500,C,
'''
        row = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "aggregate.csv", "content": report},
        ).json()["rows"][0]

        assert row["status"] == "matched"
        assert row["can_import"] is False
        assert "2 个 LEAPS 批次合计匹配" in row["message"]
        assert len(client.get("/api/positions").json()) == 2


def test_annual_and_monthly_reports_share_transaction_fingerprints_but_not_position_snapshots() -> None:
    annual = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"January 1, 2026 - August 31, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Underlying Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Stocks,USD,BOXX,,100,1,99.5,9950,100,10000,50,,,,
Deposits & Withdrawals,Header,Currency,Settle Date,Description,Amount
Deposits & Withdrawals,Data,USD,2026-08-12,Electronic Fund Transfer,25000
'''
    monthly = annual.replace(
        'January 1, 2026 - August 31, 2026',
        'September 1, 2026 - September 30, 2026',
    )

    annual_rows = parse_activity_statement(annual)
    monthly_rows = parse_activity_statement(monthly)
    annual_deposit = next(row for row in annual_rows if row.section == "Deposits & Withdrawals")
    monthly_deposit = next(row for row in monthly_rows if row.section == "Deposits & Withdrawals")
    annual_position = next(row for row in annual_rows if row.section == "Open Positions")
    monthly_position = next(row for row in monthly_rows if row.section == "Open Positions")

    assert annual_deposit.fingerprint == monthly_deposit.fingerprint
    assert annual_position.fingerprint != monthly_position.fingerprint
    assert annual_position.report_as_of.isoformat() == "2026-08-31"
    assert monthly_position.report_as_of.isoformat() == "2026-09-30"


def test_ibkr_import_classifies_boxx_and_strategy_outsiders_and_reconciles_reimported_snapshot() -> None:
    report = '''Statement,Header,Field Name,Field Value
Statement,Data,Period,"January 1, 2026 - August 26, 2026"
Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Underlying Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Expiry,Strike,Put/Call,Code
Open Positions,Data,Summary,Stocks,USD,BOXX,,200,1,99.5,19900,100,20000,100,,,,
Open Positions,Data,Summary,Stocks,USD,IBM,,10,1,250,2500,260,2600,100,,,,
Open Positions,Data,Summary,Equity and Index Options,USD,IBM  270115P00240000,IBM,1,100,12,1200,15,1500,300,2027-01-15,240,P,
'''
    with import_client() as client:
        preview = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "2026.csv", "content": report},
        ).json()
        assert preview["report_as_of"] == "2026-08-26"
        selected = [row["fingerprint"] for row in preview["rows"] if row["selected"]]
        confirmed = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "2026.csv",
                "content": report,
                "selected_fingerprints": selected,
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert confirmed.status_code == 200, confirmed.text

        listing = client.get("/api/other-holdings?include_closed=true").json()
        records = {(
            row["symbol"], row["asset_type"], row["option_type"]
        ): row for row in listing["records"]}
        assert records[("BOXX", "equity", None)]["category"] == "cash_equivalent"
        assert records[("IBM", "equity", None)]["category"] == "other"
        assert records[("IBM", "option", "put")]["direction"] == "long"
        assert listing["cash_equivalent_value"] == 20000.0
        assert listing["other_value"] == 4100.0

        cash = client.get("/api/portfolio/summary").json()["capital"]["cash"]
        assert cash["total"] == 5000.0
        assert cash["cash_equivalent"] == 20000.0
        assert cash["liquid"] == 5000.0
        assert cash["available"] == 5000.0

        boxx = records[("BOXX", "equity", None)]
        changed = client.patch(
            f"/api/other-holdings/{boxx['id']}",
            json={"quantity": 100},
        )
        assert changed.status_code == 200
        repeated = client.post(
            "/api/imports/ibkr/preview",
            json={"filename": "2026-again.csv", "content": report},
        ).json()
        boxx_row = next(row for row in repeated["rows"] if row["instrument"] == "BOXX")
        assert boxx_row["status"] == "ready"
        assert boxx_row["action"] == "update_unmanaged"
        assert "曾导入" in boxx_row["message"]
        reconciled = client.post(
            "/api/imports/ibkr/confirm",
            json={
                "filename": "2026-again.csv",
                "content": report,
                "selected_fingerprints": [boxx_row["fingerprint"]],
                "overrides": {},
                "confirmation": "IMPORT",
            },
        )
        assert reconciled.status_code == 200, reconciled.text
        updated_boxx = next(
            row
            for row in client.get("/api/other-holdings").json()["records"]
            if row["symbol"] == "BOXX"
        )
        assert updated_boxx["quantity"] == 200.0
