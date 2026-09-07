# BRK.B / VOO Rotation

The core stock portfolio must reach 98% of its account allocation target before
rotation becomes eligible. Pending puts do not count as owned shares. DCA and
the existing accumulation routing continue independently before that point.

Rules are defined in `backend/app/domain/core_rotation.py` (`RotationRules`).
These fixed thresholds are a user-selected configuration, not a backtested
claim of fair value. The P/B accelerator is disabled.

| BRK.B close / VOO close | Direction | BRK.B target weight |
| --- | --- | --- |
| >= 0.88 | BRK.B to VOO only | 30% |
| >= 0.83 and < 0.88 | BRK.B to VOO only | 55% |
| >= 0.78 and < 0.83 | BRK.B to VOO only | 80% |
| > 0.72 and < 0.78 | Hold | Current weight |
| > 0.68 and <= 0.72 | VOO to BRK.B only | 70% |
| > 0.65 and <= 0.68 | VOO to BRK.B only | 85% |
| <= 0.65 | VOO to BRK.B only | 100% |

Three consecutive completed sessions must satisfy the current threshold. A more
extreme close in the same direction confirms a less extreme threshold, but a
single jump into a deeper band does not confirm that deeper band. Market dates
are aligned across both stocks. Sample, stale, nonpositive, or misaligned data
cannot produce formal rotation alerts. Refresh remains manual.

Weights use only BRK.B and VOO stock market values, not allocated bucket capital,
cash, BOXX, or option positions. A two-percentage-point tolerance applies before
any sale. Target weights never force a transaction in the opposite direction.
An extreme band can identify a distant target without moving there in one step.

Actual core-stock sale turnover is capped at 20 percentage points in the latest
20 completed market sessions, shared by both directions. Purchases are not
counted a second time. All core sales conservatively consume capacity, even if
the matching purchase has not yet appeared in a report. Signal generation does
not consume capacity. A same-band reminder is limited to once per seven calendar
days; changed or invalidated advice is archived.

`core_trades` records IBKR stock executions with a canonical identity consisting
of symbol, execution timestamp, signed quantity, execution price, currency and
an occurrence counter. Report filenames, period boundaries, and mark prices are
not part of that identity. Daily/range reimports therefore do not consume the
same capacity twice when they include the same order-level executions.

Pre-trade quantities are reconstructed backwards from a report's ending stock
snapshot and its executions. Turnover divides actual sale proceeds by estimated
pre-trade core equity value: the sold symbol uses its execution price and the
other symbol uses its close on that trading day. This denominator is an estimate,
not an intraday account valuation. Missing snapshots/prices or unmatched legacy
snapshot reductions pause rotation rather than assuming unused capacity. A
later complete report can supply previously missing pre-trade quantities.

A full core-stock exit supported by new sale executions and an ending snapshot
closes the old holding even when the symbol no longer appears in that snapshot.
Reimporting those executions cannot close a later replacement holding.
This does not add chronological protection to unrelated legacy snapshot imports.

Pending puts are shown as a separate all-assigned weight scenario using the
same reference stock prices. Puts on the symbol proposed for sale downgrade
rotation to observation because assignment would replenish that symbol.
There is no order submission and no automatic put close or roll.
