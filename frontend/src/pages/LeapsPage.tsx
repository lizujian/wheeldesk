import { useState } from 'react'
import {
  Activity,
  BriefcaseBusiness,
  Building2,
  CalendarClock,
  CircleDashed,
  ChevronRight,
  Gauge,
  Landmark,
  ListChecks,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  WalletCards,
} from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import type { ClubEntryDecision, MarketSnapshot, OtherHolding, PortfolioSummary, Position, TrancheDecision, PMCCState } from '../lib/types'
import './LeapsPage.css'

const slotFractions = [.2, .2, .2, .2, .2]
const CLUB_DISPLAY_EXCLUSIONS = new Set(['LLY', 'BRK-B', 'BRK.B'])

export function LeapsPage({ market, positions, portfolio, leapsCalls = [] }: {
  market: MarketSnapshot | null
  positions: Position[]
  portfolio: PortfolioSummary
  leapsCalls?: OtherHolding[]
}) {
  const [view, setView] = useState<'signals' | 'holdings'>('signals')
  const leapsHistory = positions.filter((position) => position.bucket === 'leaps')
  const leaps = leapsHistory.filter((position) => position.status === 'open')
  const closedById = new Map(leapsHistory
    .filter((position) => position.status === 'closed')
    .map((position) => [position.id, position]))
  const qqqLeaps = leaps.filter((position) => !isClubPosition(position))
  const clubLeaps = leaps.filter((position) => isClubPosition(position) && !isExcludedClubSymbol(position.symbol))
  const qqqLeapsCalls = leapsCalls.filter((record) => record.symbol === 'QQQ' || record.symbol === 'QLD')
  const clubLeapsCalls = leapsCalls.filter((record) => !['QQQ', 'QLD'].includes(record.symbol) && !isExcludedClubSymbol(record.symbol))
  const clubDecisions = (market?.leaps_club?.decisions ?? []).filter((decision) => !isExcludedClubSymbol(decision.symbol))
  const pmcc = market?.pmcc
  const accountEquity = portfolio.total_equity ?? 0
  const target = pmcc?.budget.total_target ?? accountEquity * .25
  const targetFraction = .25
  const funded = (portfolio.balances?.wheel ?? 0) + (portfolio.balances?.leaps ?? 0)
  const capital = portfolio.capital?.options ?? {
    assigned: funded,
    committed: leaps.reduce((total, position) => total + position.entry_price * position.quantity * position.multiplier, 0),
    available: 0,
    cash_occupancy: 0,
  }
  const overTarget = Math.max((pmcc?.total.committed ?? capital.committed) - target, 0)
  const unfundedExposure = capital.cash_occupancy
  const fifo = market?.leaps_fifo

  return <div className="page-stack leaps-console">
    <div className="page-heading">
      <div><p className="eyebrow">QQQ / QLD + TRILLION CLUB</p><h1>LEAPS / PMCC 双策略台</h1><span>共享风险预算 · 独立信号与持仓管理</span></div>
      {market && <span className={`source-badge ${market.source}`}>{market.source === 'sample' ? '模拟数据' : '公开行情'}</span>}
    </div>

    <section className={`leaps-budget-band ${overTarget || unfundedExposure ? 'danger' : ''}`} aria-label="PMCC 预算">
      <BudgetMetric icon={WalletCards} label="PMCC 风险预算" value={target} note={`总资产 ${((targetFraction) * 100).toFixed(0)}% · QQQ 10% + 个股 15%`} />
      <BudgetMetric icon={Landmark} label="Long LEAPS 借方占用" value={pmcc?.total.committed ?? capital.committed} note={`最大损失上限 ${formatMoney(pmcc?.total.maximum_loss ?? capital.committed)}`} danger={overTarget > 0} />
      <BudgetMetric icon={Gauge} label="PMCC 可用额度" value={pmcc?.total.available ?? capital.available} note="按 Long LEAPS 成本计算" />
      <BudgetMetric icon={ShieldCheck} label="PMCC 净现金流" value={pmcc?.total.net_cash_flow ?? 0} note="已收 Short Call 权利金 - 当前买回成本" />
    </section>

    {(overTarget > 0 || unfundedExposure > 0) && <div className="leaps-budget-alert" role="alert">
      <ShieldAlert size={17} />
      <span>{overTarget > 0 && <>车轮与 LEAPS 合计成本超过共享目标 {formatMoney(overTarget)}。</>}{unfundedExposure > 0 && <>期权共享池临时占用现金 {formatMoney(unfundedExposure)}。</>}</span>
    </div>}

    {fifo?.required && fifo.candidate && <div className="leaps-fifo-alert" role="alert">
      <RefreshCw size={17} />
      <div><strong>FIFO 换仓候选：槽位 {fifo.candidate.slot}</strong><span>最早持仓 {fifo.candidate.opened_on}。如在券商完成换仓，下一份 IBKR 报表会同步槽位记录。</span></div>
    </div>}

    <section className="leaps-policy-strip" aria-label="PMCC 合约规则">
      <div><span>QQQ / QLD</span><strong>总资产 10% · Long LEAPS + Short Call</strong></div>
      <div><span>个股 PMCC 池</span><strong>总资产 15% · 单股最多 3%</strong></div>
      <div><span>QQQ Call 选约</span><strong>建议 330–400 DTE · Delta 约 0.60</strong></div>
      <div><span>PMCC 开仓</span><strong>复用 LEAPS 条件 · 先有 Long 再卖 Call</strong></div>
      <div className="guardrail"><ShieldCheck size={17} /><span>禁止 TQQQ LEAPS · 未覆盖 Call 不计 PMCC</span></div>
    </section>

    <div className="segmented-control leaps-view-tabs" role="tablist" aria-label="LEAPS 页面视图">
      <button type="button" role="tab" aria-selected={view === 'signals'} aria-controls="leaps-signals-panel" className={view === 'signals' ? 'active' : ''} onClick={() => setView('signals')}><ListChecks size={15} />股票列表 / 信号 <b>{1 + clubDecisions.length}</b></button>
      <button type="button" role="tab" aria-selected={view === 'holdings'} aria-controls="leaps-holdings-panel" className={view === 'holdings' ? 'active' : ''} onClick={() => setView('holdings')}><BriefcaseBusiness size={15} />当前持仓 <b>{leaps.length + leapsCalls.length}</b></button>
    </div>

    {view === 'signals'
      ? <section id="leaps-signals-panel" className="leaps-tab-panel" role="tabpanel" aria-label="股票列表与信号">
        <LeapsSignalStockList market={market} decisions={clubDecisions} />
      </section>
      : <section id="leaps-holdings-panel" className="leaps-tab-panel" role="tabpanel" aria-label="当前持仓">
        <LeapsHoldingsRegister
          positions={qqqLeaps}
          rollSources={closedById}
          callWheels={qqqLeapsCalls}
          marketDate={market?.as_of}
          title="QQQ / QLD 当前持仓"
          eyebrow="QQQ / QLD LIVE REGISTER"
          fifoPositionId={fifo?.required ? fifo.candidate?.position_id : null}
          emptyMessage="尚无 QQQ Call 或 QLD 持仓"
        />

        <ClubConsole market={market} positions={clubLeaps} rollSources={closedById} callWheels={clubLeapsCalls} sharedTarget={pmcc?.budget.individual_target ?? accountEquity * .15} decisions={clubDecisions} />
      </section>}
  </div>
}

function LeapsSignalStockList({ market, decisions }: { market: MarketSnapshot | null; decisions: ClubEntryDecision[] }) {
  const qqq = market?.market.qqq
  const session = market?.leaps_session
  const qqqDecision = market?.leaps?.find((decision) => decision.tranche === 1)
  const qqqPrice = session?.price ?? qqq?.price ?? null
  const qqqChange = session?.change_fraction
    ?? (session?.previous_close && qqq?.price != null && session.previous_close !== qqq.price
      ? qqq.price / session.previous_close - 1
      : null)
  const qqqReady = Boolean(market && (market.leaps_technical_ready || qqqDecision?.eligible))
  const qqqRow = {
    symbol: 'QQQ',
    name: 'Invesco QQQ',
    price: qqqPrice,
    change: qqqChange,
    ma200: qqq?.ma200 ?? null,
    rsi14: qqq?.rsi14 ?? null,
    signal: qqqReady ? '已触发' : market ? '未触发' : '等待行情',
    signalTone: qqqReady ? 'ready' : market ? 'waiting' : 'unavailable',
    note: qqqReady ? session?.price == null ? '满足条件 · 使用完成日线缓存' : '满足 QQQ LEAPS 入场条件' : market ? '等待完整技术条件' : '等待行情刷新',
  }
  const rows = [
    qqqRow,
    ...[...decisions]
      .sort((left, right) => sortByDailyDrop(clubChange(left), clubChange(right)) || left.symbol.localeCompare(right.symbol))
      .map((decision) => {
        const change = clubChange(decision)
        return {
          symbol: decision.symbol,
          name: decision.name,
          price: decision.current_price ?? decision.close,
          change,
          ma200: decision.ma200,
          rsi14: decision.rsi14,
          signal: decision.eligible ? '已触发' : decision.technical_eligible ? '技术满足' : '未触发',
          signalTone: decision.eligible ? 'ready' : decision.technical_eligible ? 'partial' : 'waiting',
          note: decision.eligible
            ? decision.suggested_slot ? `可评估槽位 ${decision.suggested_slot}` : '满足个股 LEAPS 条件'
            : decision.over_shared_budget ? '共享额度已满' : '等待完整技术条件',
        }
      }),
  ]

  return <section className="leaps-stock-list" aria-label="LEAPS 股票列表">
    <header>
      <div className="section-title"><div><p>WATCHLIST SIGNALS</p><h2>股票列表 / 信号</h2></div><span>QQQ 置顶 · 万亿俱乐部按当日跌幅排序</span></div>
    </header>
    <div className="leaps-stock-table" role="table" aria-label="LEAPS 股票信号列表">
      <div className="leaps-stock-row head" role="row">
        <span role="columnheader">股票</span><span role="columnheader">当前价</span><span role="columnheader">日涨跌</span><span role="columnheader">MA200</span><span role="columnheader">RSI14</span><span role="columnheader">LEAPS 信号</span><span role="columnheader">说明</span>
      </div>
      {rows.map((row) => <div className="leaps-stock-row" role="row" key={row.symbol}>
        <div className="leaps-stock-name" role="cell"><strong>{row.symbol}</strong><small>{row.name}</small></div>
        <strong role="cell">{formatStockPrice(row.price)}</strong>
        <strong role="cell" className={row.change != null && row.change < 0 ? 'negative' : row.change != null ? 'positive' : ''}>{formatStockChange(row.change)}</strong>
        <span role="cell">{formatStockPrice(row.ma200)}</span>
        <span role="cell">{formatStockRsi(row.rsi14)}</span>
        <span role="cell" className={`leaps-stock-status ${row.signalTone}`}>{row.signal}</span>
        <small role="cell" className="leaps-stock-note">{row.note}</small>
      </div>)}
    </div>
  </section>
}

function sortByDailyDrop(left: number | null, right: number | null) {
  return (left ?? Number.POSITIVE_INFINITY) - (right ?? Number.POSITIVE_INFINITY)
}

function clubChange(decision: ClubEntryDecision) {
  return decision.change_fraction ?? (decision.previous_close > 0 ? decision.close / decision.previous_close - 1 : null)
}

function formatStockPrice(value: number | null | undefined) {
  return value == null ? '—' : formatMoney(value)
}

function formatStockChange(value: number | null | undefined) {
  return value == null ? '—' : formatPercent(value)
}

function formatStockRsi(value: number | null | undefined) {
  return value == null ? '—' : value.toFixed(1)
}

function ClubConsole({ market, positions, rollSources, callWheels, sharedTarget, decisions }: {
  market: MarketSnapshot | null
  positions: Position[]
  rollSources: Map<number, Position>
  callWheels: OtherHolding[]
  sharedTarget: number
  decisions: ClubEntryDecision[]
}) {
  const shared = market?.pmcc?.individual
  const weeklyOpen = decisions.every((decision) => decision.checks.weekly_limit !== false)
  return <section className="club-console" aria-label="万亿俱乐部 LEAPS">
    <div className="club-rule-band">
      <div><Building2 size={17} /><span>资格门槛</span><strong>公开市值 ≥ $1T</strong><small>至少 252 个完成交易日</small></div>
      <div><Activity size={17} /><span>入场组合</span><strong>RSI14 &lt; 45 · 当日跌超 5%</strong><small>QQQ 与个股均位于 SMA200 上方</small></div>
      <div><CalendarClock size={17} /><span>本周频率</span><strong>{weeklyOpen ? '尚未确认开仓' : '本周已经执行'}</strong><small>按美股自然周统一限频</small></div>
      <div className={shared && shared.available <= 0 ? 'danger' : ''}><WalletCards size={17} /><span>个股 PMCC 池可用额度</span><strong>{formatMoney(shared?.available ?? Math.max(sharedTarget - positions.reduce((sum, position) => sum + position.current_value, 0), 0))}</strong><small>{shared && shared.over > 0 ? `已超 15% 目标 ${formatMoney(shared.over)}` : '每只个股 Long LEAPS 最多占 3%'}</small></div>
    </div>

    <LeapsHoldingsRegister
      positions={positions}
      rollSources={rollSources}
      callWheels={callWheels}
      marketDate={market?.as_of}
      title="万亿俱乐部当前持仓"
      eyebrow="CLUB LIVE REGISTER"
      emptyMessage="尚无万亿俱乐部 Long Call 持仓"
    />

  </section>
}

function LeapsHoldingsRegister({ positions, rollSources, callWheels, marketDate, title, eyebrow, fifoPositionId, emptyMessage }: {
  positions: Position[]
  rollSources: Map<number, Position>
  callWheels: OtherHolding[]
  marketDate?: string
  title: string
  eyebrow: string
  fifoPositionId?: number | null
  emptyMessage: string
}) {
  const actionable = positions.filter((position) => position.exit_decision?.actionable).length
  const clusters = groupBySymbol(positions, callWheels)
  return <section className="leaps-holdings-register" aria-label={title}>
    <header>
      <div className="section-title"><div><p>{eyebrow}</p><h2>{title}</h2></div><span>{positions.length} 笔持仓{callWheels.length ? ` · ${callWheels.length} 笔 Short Call` : ''}{actionable ? ` · ${actionable} 笔卖出信号` : ''}</span></div>
    </header>
    {clusters.length
      ? <div className="leaps-symbol-groups">{clusters.map((cluster) => <LeapsSymbolCluster cluster={cluster} rollSources={rollSources} marketDate={marketDate} fifoPositionId={fifoPositionId} key={cluster.symbol} />)}</div>
      : <div className="leaps-register-empty"><CircleDashed size={22} /><strong>{emptyMessage}</strong><span>下一次成交由 IBKR 报表自动同步</span></div>}
  </section>
}

function LeapsSymbolCluster({ cluster, rollSources, marketDate, fifoPositionId }: {
  cluster: { symbol: string; positions: Position[]; calls: OtherHolding[] }
  rollSources: Map<number, Position>
  marketDate?: string
  fifoPositionId?: number | null
}) {
  const sorted = [...cluster.positions].sort((left, right) => (left.tranche ?? 99) - (right.tranche ?? 99) || left.opened_on.localeCompare(right.opened_on))
  const activeCalls = cluster.calls.filter((call) => call.status === 'open').length
  return <section className="leaps-symbol-cluster" aria-label={`${cluster.symbol} 策略簇`}>
    <header>
      <div><span>UNDERLYING STRATEGY CLUSTER</span><h3>{cluster.symbol}</h3></div>
      <span>{sorted.length ? `${sorted.length} 笔 Long` : '无 Long'}{cluster.calls.length ? ` · ${activeCalls} 笔活动 Short Call` : ''}</span>
    </header>
    {sorted.length > 0 && <div className="leaps-lot-list">{sorted.map((position) => <LeapsPositionCard position={position} rolledFrom={position.rolled_from_position_id ? rollSources.get(position.rolled_from_position_id) : undefined} rollSources={rollSources} marketDate={marketDate} fifoCandidate={position.id === fifoPositionId} key={position.id} />)}</div>}
    <LeapsCallWheelRegister calls={cluster.calls} />
  </section>
}

function LeapsCallWheelRegister({ calls }: { calls: OtherHolding[] }) {
  const active = calls.filter((call) => call.status === 'open')
  const history = calls.filter((call) => call.status !== 'open')
  const realizedProfit = history.reduce((total, call) => total + (call.realized_profit ?? 0), 0)
  if (!calls.length) return null
  return <section className="leaps-call-wheel-register" aria-label="PMCC Short Call">
    <header><div><p>PMCC CASH FLOW</p><h3>PMCC Short Call</h3></div><span>{active.length} 笔活动{history.length ? ` · ${history.length} 笔历史` : ''} · 累计已实现盈亏 {formatMoney(realizedProfit)}</span></header>
    {active.map((call) => <LeapsCallWheelCard call={call} key={call.id} />)}
    {history.length > 0 && <details><summary>查看已平仓 Sell Call（{history.length} 笔）</summary>{history.map((call) => <LeapsCallWheelCard call={call} key={call.id} />)}</details>}
  </section>
}

function LeapsCallWheelCard({ call }: { call: OtherHolding }) {
  const open = call.status === 'open'
  const profit = open ? call.unrealized_profit : call.realized_profit
  const value = call.current_value == null ? null : Math.abs(call.current_value)
  const pmcc = call.pmcc_state
  return <article className={`leaps-call-wheel-card ${profit != null && profit < 0 ? 'loss' : ''}`} aria-label={`${call.symbol} PMCC Short Call ${call.id}`}>
    <div className="leaps-call-wheel-title"><b>{call.symbol}</b><strong>${call.strike ?? '—'} Call</strong><span>{open ? pmccStatusLabel(pmcc?.status) : `已${call.status === 'closed' ? '平仓' : '结束'}`}</span></div>
    <div><small>合约</small><strong>{call.quantity} 张</strong></div>
    <div><small>收取权利金 / 股</small><strong>{formatMoney(call.entry_price ?? 0)}</strong></div>
    <div><small>{open ? '当前买回价' : '退出价格'}</small><strong>{formatMoney((open ? call.current_price : call.exit_price) ?? 0)}</strong></div>
    <div><small>{open ? '净现金流' : '已实现盈亏'}</small><strong>{open ? formatMoney(pmcc?.net_cash_flow ?? (call.entry_price ?? 0) * call.quantity * call.multiplier - value!) : formatMoney(profit ?? 0)}</strong></div>
    <div><small>到期日</small><strong>{call.expiration ?? '—'}</strong></div>
    {call.linked_position_id && <><small className="leaps-call-wheel-link">关联 Long Call #{call.linked_position_id}</small><small className="leaps-call-wheel-link">覆盖 {pmcc ? `${(pmcc.coverage_ratio * 100).toFixed(0)}%` : '待核对'}</small></>}
    {pmcc && <small className="leaps-call-wheel-link">最大损失 {formatMoney(pmcc.maximum_loss)} · Short DTE {pmcc.short_dte ?? '—'}{pmcc.assignment_risk ? ' · 行权风险' : ''}</small>}
  </article>
}

function groupBySymbol(positions: Position[], calls: OtherHolding[]) {
  const groups = new Map<string, { symbol: string; positions: Position[]; calls: OtherHolding[] }>()
  const ensure = (symbol: string) => {
    const existing = groups.get(symbol)
    if (existing) return existing
    const created = { symbol, positions: [], calls: [] }
    groups.set(symbol, created)
    return created
  }
  positions.forEach((position) => ensure(position.symbol).positions.push(position))
  calls.forEach((call) => ensure(call.symbol).calls.push(call))
  return [...groups.values()]
}

function LeapsPositionCard({ position, rolledFrom, rollSources, marketDate, fifoCandidate }: { position: Position; rolledFrom?: Position; rollSources: Map<number, Position>; marketDate?: string; fifoCandidate: boolean }) {
  const cost = position.entry_price * position.quantity * position.multiplier
  const returnFraction = position.exit_decision?.return_fraction
    ?? (position.unrealized_profit == null || cost <= 0 ? null : position.unrealized_profit / cost)
  const actionable = Boolean(position.exit_decision?.actionable)
  const status = fifoCandidate ? 'FIFO 待轮动' : actionable ? '卖出信号' : '持仓中'
  const isEquity = position.asset_type === 'equity'
  const quote = isEquity ? position.current_price : position.quote_bid ?? position.current_price
  const heldDays = position.exit_decision?.days_held ?? daysBetween(position.opened_on, marketDate)
  const dte = position.exit_decision?.dte ?? daysUntil(position.expiration, marketDate)
  const accumulatedRealized = rolledFrom ? sumHistoricalRealizedProfit(rolledFrom, rollSources) : 0
  const historicalRollCount = rolledFrom ? countHistoricalRolls(rolledFrom, rollSources) : 0
  return <article className={`leaps-lot ${actionable ? 'exit-ready' : ''} ${fifoCandidate ? 'fifo-candidate' : ''}`} aria-label={`LEAPS 持仓 ${position.id}`}>
    <header>
      <div><span>槽位 {position.tranche ?? '—'} · {isEquity ? 'QLD 平替仓' : isClubPosition(position) ? '万亿俱乐部' : 'QQQ LEAPS'}</span><h3><b className="lot-symbol">{position.symbol}</b>{isEquity ? '正股' : `$${position.strike} Call`} #{position.id}</h3></div>
      <strong className={`state-badge ${fifoCandidate ? 'fifo' : actionable ? 'actionable' : 'open'}`}>{status}</strong>
    </header>

    <div className="leaps-lot-values">
      <LotMetric label={isEquity ? '持股数量' : '合约数量'} value={`${position.quantity} ${isEquity ? '股' : '张'}`} />
      <LotMetric label={isEquity ? '成本 / 股' : '权利金 / 股'} value={formatMoney(position.entry_price)} />
      <LotMetric label={isEquity ? '当前价格' : position.quote_bid == null ? '当前估值' : '当前 Bid'} value={quote == null ? '等待报价' : formatMoney(quote)} />
      <LotMetric label="当前市值" value={formatMoney(position.current_value)} />
      <LotMetric label="当前收益" value={returnFraction == null ? '等待报价' : formatPercent(returnFraction)} tone={returnFraction != null && returnFraction < 0 ? 'loss' : 'gain'} />
      <LotMetric label={isEquity ? '持有时间' : '到期 / DTE'} value={isEquity ? `${heldDays} 天` : `${position.expiration ?? '—'} · ${dte} DTE`} />
    </div>

    {rolledFrom
      ? <LeapsRollSummary position={position} rolledFrom={rolledFrom} accumulatedRealized={accumulatedRealized} historicalRollCount={historicalRollCount} />
      : position.rolled_from_position_id && <div className="leaps-roll-link"><RefreshCw size={16} /><div><span>展期关系</span><strong>由持仓 #{position.rolled_from_position_id} 展期至当前合约</strong></div></div>}

  </article>
}

function LeapsRollSummary({ position, rolledFrom, accumulatedRealized, historicalRollCount }: { position: Position; rolledFrom: Position; accumulatedRealized: number; historicalRollCount: number }) {
  const contractQuantity = position.quantity
  const netDebit = (position.entry_price - rolledFrom.current_price) * contractQuantity * position.multiplier
  const realized = rolledFrom.realized_profit ?? 0
  const netLabel = netDebit >= 0 ? '净支出' : '净收入'
  return <details className="leaps-roll-summary" aria-label={`${position.symbol} 展期记录 ${rolledFrom.id} 到 ${position.id}`}>
    <summary className="leaps-roll-heading">
      <ChevronRight size={16} className="leaps-roll-chevron" />
      <div><span>LEAPS 历史展期</span><strong>查看已平仓展期记录（{historicalRollCount} 笔） · 累计已实现盈亏 {formatMoney(accumulatedRealized)}</strong></div>
    </summary>
    <div className="leaps-roll-metrics">
      <div><span>展期前合约</span><strong>{rolledFrom.expiration ?? '—'} ${rolledFrom.strike ?? '—'} Call</strong><small>持仓 #{rolledFrom.id} → #{position.id}</small></div>
      <div><span>旧腿平仓</span><strong>平仓 {formatMoney(rolledFrom.current_price)}</strong><small>原权利金 {formatMoney(rolledFrom.entry_price)}</small></div>
      <div><span>旧腿损益</span><strong>已实现 {formatMoney(realized)}</strong><small>已计入 LEAPS 已实现流水</small></div>
      <div><span>展期资金</span><strong>{netLabel} {formatMoney(Math.abs(netDebit))}</strong><small>新权利金 {formatMoney(position.entry_price)}</small></div>
    </div>
  </details>
}

function sumHistoricalRealizedProfit(source: Position, rollSources: Map<number, Position>) {
  return historicalRolls(source, rollSources).reduce((total, position) => total + (position.realized_profit ?? 0), 0)
}

function countHistoricalRolls(source: Position, rollSources: Map<number, Position>) {
  return historicalRolls(source, rollSources).length
}

function historicalRolls(source: Position, rollSources: Map<number, Position>) {
  const history: Position[] = []
  let current: Position | undefined = source
  const visited = new Set<number>()
  while (current && !visited.has(current.id)) {
    visited.add(current.id)
    history.push(current)
    current = current.rolled_from_position_id ? rollSources.get(current.rolled_from_position_id) : undefined
  }
  return history
}

function LotMetric({ label, value, tone = '' }: { label: string; value: string; tone?: string }) {
  return <div><span>{label}</span><strong className={tone}>{value}</strong></div>
}

function BudgetMetric({ icon: Icon, label, value, note, danger = false }: { icon: typeof WalletCards; label: string; value: number; note: string; danger?: boolean }) {
  return <div className={danger ? 'danger' : ''}><Icon size={18} /><span>{label}</span><strong>{formatMoney(value)}</strong><small>{note}</small></div>
}

function defaultDecisions(): TrancheDecision[] {
  return slotFractions.map((fraction, index) => ({ tranche: index + 1, eligible: false, allocation_fraction: fraction, suggested_amount: 0, checks: {} }))
}

function pmccStatusLabel(status?: PMCCState['status']) {
  if (status === 'covered') return '已覆盖'
  if (status === 'needs_roll') return '进入展期窗口'
  if (status === 'assignment_risk') return '行权风险'
  if (status === 'expired') return '已到期'
  return '未覆盖 / 待核对'
}

function isClubPosition(position: Position) {
  if (position.leaps_category) return position.leaps_category === 'club'
  return position.bucket === 'leaps' && position.symbol !== 'QQQ' && position.symbol !== 'QLD'
}

function isExcludedClubSymbol(symbol: string) {
  return CLUB_DISPLAY_EXCLUSIONS.has(symbol.toUpperCase())
}

function daysUntil(value: string | null, asOf?: string) {
  if (!value) return '—'
  return Math.max(0, Math.ceil((new Date(value).getTime() - new Date(asOf ?? today()).getTime()) / 86400000))
}

function daysBetween(value: string, asOf?: string) {
  return Math.max(0, Math.floor((new Date(asOf ?? today()).getTime() - new Date(value).getTime()) / 86400000))
}

function formatPercent(value: number) { return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%` }
function today() { return new Date().toISOString().slice(0, 10) }
