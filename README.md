# WheelDesk

WheelDesk is a local, single-user portfolio and options-strategy monitor. It
imports Interactive Brokers Activity Statement CSV files, keeps an idempotent
local ledger, refreshes public market data on demand, and presents decision
support for core equity, Wheel, and LEAPS strategies.

WheelDesk does not connect to a brokerage trading API, submit orders, or infer
that a suggested trade was executed. Broker statements remain the source of
truth for positions and transactions.

## Features

- Four-bucket allocation monitoring for core equity, cash, Wheel, and LEAPS.
- Incremental IBKR Activity Statement imports with duplicate detection.
- BOXX recognition as a cash equivalent and separate unmanaged-position views.
- TQQQ and trillion-club Wheel monitoring, including rolls and realized P/L.
- QQQ/QLD and trillion-club LEAPS monitoring, including FIFO roll history.
- Core BRK.B/VOO accumulation signals and periodic account rebalancing prompts.
- Manually triggered Yahoo market refreshes for daily indicators and quotes.
- Local-only SQLite persistence with no cloud synchronization.

## Privacy And Security

This application is intentionally bound to `127.0.0.1` and has no login or
authorization layer. Do not expose either development port to a LAN or the
public internet.

IBKR statements are parsed locally in the browser/API workflow. Imported rows,
positions, cash balances, and account history are stored in
`data/wheeldesk.db`. The repository ignores `data/`, CSV exports, local reports,
environment files, virtual environments, build output, and browser-test
artifacts. Keep database backups and broker reports outside the repository and
protect them separately.

See [SECURITY.md](SECURITY.md) for the public-repository disclosure policy and
deployment constraints.

## Requirements

- Python 3.12+
- Node.js 22+
- pnpm 10+
- Google Chrome, for the default one-click launch flow

## Install

```bash
make install
```

## Run

```bash
./start.sh
```

The launcher starts the API and frontend, waits for both services, and opens
Google Chrome automatically. Keep the terminal open; `Ctrl+C` stops both
services.

- Web UI: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000`

Use `make dev` to start both services without opening a browser.

## Data Workflow

1. Initialize a local profile with an age, opening equity, and opening date.
2. Export an Activity Statement CSV from Interactive Brokers.
3. Open the IBKR import page and select the CSV.
4. WheelDesk imports supported rows immediately and reports unsupported rows.
5. Import later daily, monthly, or overlapping statements as needed. Stable
   fingerprints prevent duplicate transactions while newer position snapshots
   update current values.
6. Use the refresh button when updated public market indicators are needed.

The allocation formula is configurable in code and currently assigns core
equity to `min(age + 20, 80)%`, cash to `5%`, LEAPS to `25%`, and the remaining
capacity to Wheel. Wheel and LEAPS share the options capital pool for exposure
and Margin warnings while retaining separate operational views.

## Testing

```bash
make test
cd frontend && pnpm test:e2e
```

Backend and frontend unit tests use isolated databases. Playwright creates a
unique database under `/tmp` and never uses `data/wheeldesk.db`.

## Backup

Stop the local services before copying `data/wheeldesk.db`. Do not commit the
database or a broker statement to Git, even in a private branch.

## Disclaimer

WheelDesk is personal decision-support software, not investment, tax, legal,
or brokerage advice. All signals are informational. Review market data and
confirm every action independently with the broker.
