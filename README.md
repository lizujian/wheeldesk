# WheelDesk

WheelDesk is a local, single-user portfolio and options-strategy monitor. It
imports Interactive Brokers Activity Statement CSV files, keeps an idempotent
local ledger, refreshes IBKR market data on demand, and presents decision
support for core equity, Wheel, and LEAPS/PMCC strategies.

**IB Gateway is required for normal use. Start Gateway, log in to your IBKR
account, enable its socket API with Read-Only API checked, and connect WheelDesk
through Settings before refreshing market data.** IB Gateway is the only
production data source; there is no Yahoo or Futu fallback. Without an active
connection, fresh quotes, IV and market-based strategy updates are unavailable;
saved local records remain accessible.

WheelDesk uses the IBKR API only to read market data and reconcile current
position quantities. It does not submit orders or infer that a suggested trade
was executed. Broker statements remain the source of truth for positions and
transactions.

## Features

- Four-bucket allocation monitoring for core equity, cash, Wheel, and LEAPS.
- Incremental IBKR Activity Statement imports with duplicate detection.
- BOXX recognition as a cash equivalent and separate unmanaged-position views.
- TQQQ and trillion-club Wheel monitoring, including rolls and realized P/L.
- QQQ/QLD, DRAM/SOXX and trillion-club LEAPS/PMCC monitoring, including FIFO roll history.
- Core BRK.B/VOO/SCHD accumulation signals, capped acquisition Puts, and periodic account rebalancing prompts.
- IB Gateway market refreshes on page load or manual request, including VIX, configured in Settings.
- LEAPS watchlist with QQQ, DRAM and SOXX pinned first, plus underlying IV, its
  latest available date and relative change against the previous trading date.
- Per-symbol LEAPS cost occupancy with PMCC net cash flow in parentheses, updated only on full refresh.
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
- IB Gateway installed, running and logged in to an IBKR account
- Gateway socket API enabled with Read-Only API checked, and API market-data
  permissions for the instruments used (real-time data requires the relevant
  IBKR subscriptions; available delayed/frozen data is also supported)

## Install

```bash
make install
```

## Run

1. Start IB Gateway and log in to your IBKR account. Enable its socket API,
   keep **Read-Only API** checked, and allow local connections.
2. Start WheelDesk:

   ```bash
   ./start.sh
   ```

3. Open **Settings → Market connection**, enter the Gateway host, socket port
   and a nonzero Client ID, then save and test the connection. For a local live
   Gateway, the usual host/port is `127.0.0.1:4001`; paper Gateway usually uses
   port `4002`. Match the port configured in your Gateway.
4. Keep Gateway running and logged in while using WheelDesk. The launcher starts
   WheelDesk services; it does not start or log in to Gateway.

The launcher starts the API and frontend, waits for both services, and opens
Google Chrome automatically. Keep the terminal open; `Ctrl+C` stops both
services.

- Web UI: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8000`

Use `make dev` to start both services without opening a browser.

## Market Data Settings

IB Gateway is the only production market-data source. Open **Settings →
Market connection**, set its host/port/Client ID, and test the connection.
Settings persist in the local SQLite database. Log in through Gateway or TWS
and keep Read-Only API enabled; the compatible TWS socket API can also be used.
WheelDesk stores no broker password.
Stocks, ETFs, options and the CBOE VIX index use IBKR. Yahoo and Futu integrations
have been removed. Without a configured, logged-in Gateway the app reports a
connection/setup error.

The app performs a full refresh, including underlying IV and held option quotes, immediately on first
visit or browser reload. Manual Refresh and in-app navigation update only stocks,
ETFs, VIX, price indicators and signals. They preserve the previous underlying IV
and its actual dates, as well as option valuations and their original source,
quality, timestamps and errors; PMCC risk is recomputed
with current underlying prices. Navigation refreshes when at least 60 seconds
have elapsed since the previous refresh started. Manual Refresh bypasses this
interval; all triggers share one in-flight
request. Failed attempts count toward the navigation interval to prevent repeated
requests when Gateway is unavailable. Cached data remains visible while a request
runs; no periodic background refresh runs.
Delayed and frozen quotes are accepted for valuation
and labelled with their actual quality and retrieval time. Failed quotes keep the
last valuation and its original source/time; no other vendor or sample-price
fallback is used. Indicators, including the VIX strategy threshold, use completed
daily bars. Current delayed VIX quotes are also available in connection diagnostics.

The trillion-club watchlist is maintained manually in Settings (comma or newline
separated ticker symbols). No market-cap requests or automatic membership screens
run. Removing a member stops its entry signals and preserves existing holdings.
Earnings-date requests and earnings-based entry/confirmation gates are currently
disabled at the user's request.

See [IB Gateway setup and validation](docs/ibkr-gateway.md) for API permissions,
time/quality semantics and the read-only capability check.

Each IBKR refresh compares current broker quantities against the local ledger.
It does not create trades or replace activity-statement imports. Automating complete
report imports requires a separate Flex Web Service integration.

## Data Workflow

1. Initialize a local profile with an age, opening equity, and opening date.
2. Export an Activity Statement CSV from Interactive Brokers.
3. Open the IBKR import page and select the CSV.
4. WheelDesk imports supported rows immediately and reports unsupported rows.
5. Import later daily, monthly, or overlapping statements as needed. Stable
   fingerprints prevent duplicate transactions while newer position snapshots
   update current values.
6. Keep IB Gateway connected and use **Refresh** for updated stock/ETF and VIX
   data. Reload the browser page for a full refresh, including underlying IV,
   held option quotes and per-symbol holding occupancy.

The allocation formula is configurable in code and currently assigns `70%` to
core equity, `5%` to cash, and `25%` to the shared options pool. Wheel and LEAPS
retain separate operational views, but new option capacity is reserved for the
LEAPS/PMCC transition; existing Wheel positions are not automatically closed.

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
