# Security Policy

## Supported Use

WheelDesk is a local, single-user application. The backend and frontend are
bound to `127.0.0.1` by default and do not implement authentication,
authorization, TLS termination, multi-user isolation, or internet-facing rate
limits.

Do not expose ports `5173` or `8000` to a LAN or the public internet. A public
GitHub repository makes the source code public; it does not make a locally
running WheelDesk instance safe to deploy publicly.

## Sensitive Data

Never include any of the following in an issue, pull request, test fixture, or
commit:

- IBKR account identifiers or unredacted Activity Statements
- SQLite databases or database backups
- Position exports, transaction history, balances, or tax documents
- API keys, access tokens, passwords, cookies, or `.env` files
- Screenshots that contain real account values or positions

Use synthetic symbols, dates, quantities, and prices when reporting importer
bugs. Before attaching a statement fragment, remove account identifiers and
replace all financial values with synthetic values that still reproduce the
parser behavior.

## Reporting A Vulnerability

Do not open a public issue containing sensitive account data. Report a security
problem through GitHub's private vulnerability reporting feature when it is
available for the repository. Include only the minimum synthetic reproduction
needed to demonstrate the issue.
