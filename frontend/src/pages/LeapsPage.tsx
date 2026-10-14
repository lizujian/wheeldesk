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
import { marketSourceLabel, quoteDescription } from '../lib/market'
import type { ClubEntryDecision, ImpliedVolatilityComparison, LeapsWatchlistEntry, MarketSnapshot, OtherHolding, PortfolioSummary, Position, TrancheDecision, PMCCState } from '../lib/types'
import './LeapsPage.css'

const slotFractions = [.2, .2, .2, .2, .2]
const CLUB_DISPLAY_EXCLUSIONS = new Set(['LLY', 'BRK-B', 'BRK.B'])
const PINNED_SYMBOLS = ['QQQ', 'DRAM', 'SOXX']
const ADDITIONAL_ETFS = ['DRAM', 'SOXX']

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
  const qqqLeaps = leaps.filter((position) => ['QQQ', 'QLD'].includes(position.symbol))
  const etfLeaps = leaps.filter((position) => ADDITIONAL_ETFS.includes(position.symbol))
  const clubLeaps = leaps.filter((position) => isClubPosition(position) && !isExcludedClubSymbol(position.symbol))
  const qqqLeapsCalls = leapsCalls.filter((record) => record.symbol === 'QQQ' || record.symbol === 'QLD')
  const etfLeapsCalls = leapsCalls.filter((record) => ADDITIONAL_ETFS.includes(record.symbol))
  const clubLeapsCalls = leapsCalls.filter((record) => !['QQQ', 'QLD', ...ADDITIONAL_ETFS].includes(record.symbol) && !isExcludedClubSymbol(record.symbol))
  const clubDecisions = (market?.leaps_club?.decisions ?? []).filter((decision) => !isExcludedClubSymbol(decision.symbol) && !ADDITIONAL_ETFS.includes(decision.symbol))
  const stockDecisions = [...clubDecisions, ...(market?.leaps_etfs?.decisions ?? [])]
  const stockCount = market?.leaps_watchlist?.filter((row) => !isExcludedClubSymbol(row.symbol)).length
    ?? 3 + clubDecisions.filter((row) => !PINNED_SYMBOLS.includes(row.symbol)).length
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
      <div><p className="eyebrow">QQQ / QLD + DRAM / SOXX + TRILLION CLUB</p><h1>LEAPS / PMCC 双策略台</h1><span>共享风险预算 · 独立信号与持仓管理</span></div>
      {market && <span className={`source-badge ${market.source}`}>{marketSourceLabel(market)}</span>}
    </div>

    <section className={`leaps-budget-band ${overTarget || unfundedExposure ? 'danger' : ''}`} aria-label="PMCC 预算">
      <BudgetMetric icon={WalletCards} label="PMCC 风险预算" value={target} note={`总资产 ${((targetFraction) * 100).toFixed(0)}% · QQQ 10% + 个股 15%`} />
      <BudgetMetric icon={Landmark} label="Long LEAPS 借方占用" value={pmcc?.total.committed ?? capital.committed} note={`最大损失上限 ${formatMoney(pmcc?.total.maximum_loss ?? capital.committed)}`} danger={overTarget > 0} />
      <BudgetMetric icon={Gauge} label="PMCC 可用额度" value={pmcc?.total.available ?? capital.available} note="按 Long LEAPS 成本计算" />
      <BudgetMetric icon={ShieldCheck} label="PMCC 净现金流" value={pmcc?.total.net_cash_flow ?? 0} note="已收 Short Call 权利金 - 当前买回成本" />
    </section>

    <VixContext market={market} />

    {(overTarget > 0 || unfundedExposure > 0) && <div className="leaps-budget-alert" role="alert">
      <ShieldAlert size={17} />
      <span>{overTarget > 0 && <>车轮与 LEAPS 合计成本超过共享目标 {formatMoney(overTarget)}。</>}{unfundedExposure > 0 && <>期权共享池临时占用现金 {formatMoney(unfundedExposure)}。</>}</span>
    </div>}

    {fifo?.required && fifo.candidate && <div className="leaps-fifo-alert" role="alert">
      <RefreshCw size={17} />
      <div><strong>FIFO 换仓候选：槽位 {fifo.candidate.slot}</strong><span>最早持仓 {fifo.candidate.opened_on}。如在券商完成换仓，下一份 IBKR 报表会同步槽位记录。</span></div>
    </div>}

    <div className="segmented-control leaps-view-tabs" role="tablist" aria-label="LEAPS 页面视图">
      <button type="button" role="tab" aria-selected={view === 'signals'} aria-controls="leaps-signals-panel" className={view === 'signals' ? 'active' : ''} onClick={() => setView('signals')}><ListChecks size={15} />股票列表 <b>{stockCount}</b></button>
      <button type="button" role="tab" aria-selected={view === 'holdings'} aria-controls="leaps-holdings-panel" className={view === 'holdings' ? 'active' : ''} onClick={() => setView('holdings')}><BriefcaseBusiness size={15} />当前持仓 <b>{leaps.length + leapsCalls.length}</b></button>
    </div>

    {view === 'signals'
      ? <section id="leaps-signals-panel" className="leaps-tab-panel" role="tabpanel" aria-label="股票行情与 IV">
        <LeapsStockList market={market} decisions={stockDecisions} />
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

        {(etfLeaps.length > 0 || etfLeapsCalls.length > 0) && <LeapsHoldingsRegister
          positions={[...etfLeaps].sort((a, b) => ADDITIONAL_ETFS.indexOf(a.symbol) - ADDITIONAL_ETFS.indexOf(b.symbol))}
          rollSources={closedById}
          callWheels={[...etfLeapsCalls].sort((a, b) => ADDITIONAL_ETFS.indexOf(a.symbol) - ADDITIONAL_ETFS.indexOf(b.symbol))}
          marketDate={market?.as_of}
          title="DRAM / SOXX 当前持仓"
          eyebrow="SECTOR ETF PMCC REGISTER"
          emptyMessage="尚无 DRAM / SOXX Long Call 持仓"
        />}

        <ClubConsole market={market} positions={clubLeaps} rollSources={closedById} callWheels={clubLeapsCalls} sharedTarget={pmcc?.budget.individual_target ?? accountEquity * .15} decisions={clubDecisions} />
      </section>}
  </div>
}

function VixContext({ market }: { market: MarketSnapshot | null }) {
  const context = market?.vix_context
  const price = context?.price ?? market?.market.vix.price
  const priceKind = context?.price_kind === 'snapshot' ? '刷新时行情' : '最近收盘'
  const quality = context?.quality === 'delayed' ? ' · 延迟' : context?.quality === 'closed' ? ' · 冻结' : ''
  const date = context?.price_kind === 'snapshot'
    ? (context.market_as_of ?? context.fetched_at)?.slice(0, 10)
    : context?.close_as_of ?? market?.market.vix.as_of
  const percentile = context?.percentile_fraction
  return <section className="leaps-vix-band" aria-label="VIX 市场环境">
    <div title={context?.error ?? undefined}><span><Activity size={14} />VIX 当前值</span><strong>{price == null ? '—' : price.toFixed(2)}</strong><small>{priceKind}{quality}{date ? ` · ${date}` : ''}</small></div>
    <div title={context?.history_error ?? undefined}><span>VIX 52 周最高值</span><strong>{context?.high_52w == null ? '—' : context.high_52w.toFixed(2)}</strong><small>{context?.high_52w_as_of ? `日内最高 · ${context.high_52w_as_of}` : '等待完整历史数据'}</small></div>
    <div title="分位 = 近 52 周收盘值小于或等于当前 VIX 的交易日数 ÷ 有效交易日数"><span>VIX 52 周分位</span><strong>{percentile == null ? '—' : `${(percentile * 100).toFixed(1)}%`}</strong><small>{percentile == null ? '等待完整历史数据' : `高于或等于 ${ (percentile * 100).toFixed(1)}% 的历史收盘值 · ${context?.sample_size} 日样本`}</small></div>
    <p>{context ? `${context.window_start} 至 ${context.window_end} · ` : ''}分位按近 52 周已完成交易日收盘值计算，52 周最高值取日内高点。{context?.history_error && <span>{context.history_error}</span>}</p>
  </section>
}

function LeapsStockList({ market, decisions }: { market: MarketSnapshot | null; decisions: ClubEntryDecision[] }) {
  const qqq = market?.market.qqq
  const session = market?.leaps_session
  const qqqPrice = session?.price ?? qqq?.price ?? null
  const qqqChange = session?.change_fraction
    ?? (session?.previous_close && qqq?.price != null && session.previous_close !== qqq.price
      ? qqq.price / session.previous_close - 1
      : null)
  const qqqRow: LeapsWatchlistEntry = {
    symbol: 'QQQ',
    name: 'Invesco QQQ',
    price: qqqPrice,
    change_fraction: qqqChange,
    ma200: qqq?.ma200 ?? null,
    rsi14: qqq?.rsi14 ?? null,
    source: session?.source ?? null, error: null, iv: null, iv_error: null,
  }
  const available = market?.leaps_watchlist ?? [qqqRow, ...decisions.map((decision): LeapsWatchlistEntry => ({
    symbol: decision.symbol, name: decision.name, price: decision.current_price ?? decision.close,
    change_fraction: clubChange(decision), ma200: decision.ma200, rsi14: decision.rsi14,
    source: null, error: null, iv: null, iv_error: null,
  }))]
  const bySymbol = new Map(available.map((row) => [row.symbol, row]))
  const rows = [
    ...PINNED_SYMBOLS.map((symbol) => bySymbol.get(symbol) ?? { ...qqqRow, symbol, name: symbol, price: null, change_fraction: null, ma200: null, rsi14: null }),
    ...available.filter((row) => !PINNED_SYMBOLS.includes(row.symbol) && !isExcludedClubSymbol(row.symbol))
      .sort((left, right) => sortByDailyDrop(left.change_fraction, right.change_fraction) || left.symbol.localeCompare(right.symbol)),
  ]

  return <section className="leaps-stock-list" aria-label="LEAPS 股票列表">
    <header>
      <div className="section-title"><div><p>WATCHLIST</p><h2>股票列表</h2></div><span>QQQ / DRAM / SOXX 置顶 · 个股按当日跌幅排序</span></div>
    </header>
    <div className="leaps-stock-table" role="table" aria-label="LEAPS 股票行情列表">
      <div className="leaps-stock-row head" role="row">
        <span role="columnheader">股票</span><span role="columnheader">当前价</span><span role="columnheader">日涨跌</span><span role="columnheader">RSI14</span><span role="columnheader">IV</span><span role="columnheader">当前持仓占用</span><span role="columnheader">说明</span>
      </div>
      {rows.map((row) => <div className="leaps-stock-row" role="row" key={row.symbol}>
        <div className="leaps-stock-name" role="cell"><strong>{row.symbol}</strong><small>{row.name}</small></div>
        <div role="cell" className="leaps-stock-price" title={row.session_error ?? row.error ?? undefined}>
          <div><strong>{formatStockPrice(row.price)}</strong><Ma200Comparison row={row} /></div>
          <StockSession row={row} stale={market?.stale ?? false} />
        </div>
        <strong role="cell" className={row.change_fraction != null && row.change_fraction < 0 ? 'negative' : row.change_fraction != null ? 'positive' : ''}>{formatStockChange(row.change_fraction)}</strong>
        <span role="cell">{formatStockRsi(row.rsi14)}</span>
        <IvCell iv={row.iv} error={row.iv_error} />
        <HoldingOccupancyCell occupancy={row.holding_occupancy} />
        <EntryExplanation row={row} market={market} decision={decisions.find((decision) => decision.symbol === row.symbol)} />
      </div>)}
    </div>
  </section>
}

function Ma200Comparison({ row }: { row: LeapsWatchlistEntry }) {
  const difference = row.price != null && row.ma200 != null && row.ma200 > 0 ? row.price / row.ma200 - 1 : null
  const title = row.ma200 != null ? `MA200 ${formatStockPrice(row.ma200)}；相对距离 = 当前价 / MA200 − 1`
    : row.completed_sessions != null ? `仅有 ${row.completed_sessions} 个完成交易日，MA200 需要 200 日` : '暂无 MA200 数据'
  return <span title={title} className={`leaps-ma-distance ${difference != null && difference > 0 ? 'positive' : difference != null && difference < 0 ? 'negative' : ''}`}>{difference == null ? '（MA200 暂缺）' : `（${formatPercent(difference)}）`}</span>
}

function StockSession({ row, stale }: { row: LeapsWatchlistEntry; stale: boolean }) {
  if (!row.session && !row.price_kind) return null
  const labels: Record<string, string> = { pre: '盘前', regular: '日盘', post: '盘后', overnight: '夜盘', closed: '收市', unknown: '时段待确认' }
  const quoteSession = labels[row.session ?? 'unknown'] ?? '时段待确认'
  const currentSession = labels[row.market_session ?? '']
  const label = row.price_kind === 'close' ? '最近收盘'
    : row.session === 'unknown' ? `${currentSession ?? '当前'}时段 · 成交时间未知`
    : row.market_session && row.market_session !== row.session ? `最近${quoteSession}成交` : quoteSession
  const quality = stale ? '旧值' : row.quality === 'delayed' ? '延迟' : row.quality === 'closed' ? '冻结' : null
  const time = row.market_as_of && row.price_kind !== 'close'
    ? new Date(row.market_as_of).toLocaleTimeString('zh-CN', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false }) : null
  return <small title={row.market_as_of ? `成交时间 ${row.market_as_of}` : row.fetched_at ? `获取时间 ${row.fetched_at}，成交时间未知` : undefined}>
    {[label, quality, time].filter(Boolean).join(' · ')}{row.session_error && <span>夜盘报价暂缺</span>}
  </small>
}

function IvCell({ iv, error }: { iv: ImpliedVolatilityComparison | null; error: string | null }) {
  const point = iv?.latest
  const change = iv?.change_fraction
  return <div role="cell" className="leaps-stock-iv" title={error ?? undefined}>
    <div><strong>{point ? `${(point.value * 100).toFixed(2)}%` : '—'}</strong>
      {change != null && <span className={`leaps-iv-change ${change > 0 ? 'positive' : change < 0 ? 'negative' : ''}`} title="相较前一交易日 IV 的百分比变化">{change > 0 ? '↑ ' : change < 0 ? '↓ ' : ''}{change === 0 ? '0.00%' : formatPercent(change)}</span>}
    </div>
    {point ? <time dateTime={point.as_of}>{point.as_of}</time> : <small>暂无 IV</small>}
  </div>
}

function HoldingOccupancyCell({ occupancy }: { occupancy: LeapsWatchlistEntry['holding_occupancy'] }) {
  if (!occupancy) return <span role="cell">-</span>
  const cashFlow = occupancy.net_cash_flow
  return <div role="cell" className="leaps-stock-occupancy" title="Long LEAPS 成本占用（已收 Short Call 权利金 - 当前买回成本）；全量刷新时更新">
    <strong>{formatMoney(occupancy.committed)}</strong><span className={cashFlow > 0 ? 'positive' : cashFlow < 0 ? 'negative' : ''}>（{cashFlow > 0 ? '+' : ''}{formatMoney(cashFlow)}）</span>
  </div>
}

function EntryExplanation({ row, market, decision }: { row: LeapsWatchlistEntry; market: MarketSnapshot | null; decision?: ClubEntryDecision }) {
  const qqqDecision = market?.leaps.find((item) => item.checks.next_slot) ?? market?.leaps[0]
  const signal = row.symbol === 'QQQ' ? qqqDecision : decision
  if (!signal) return <div role="cell" className="leaps-entry-explanation"><span>未满足：{row.ma200 == null ? 'MA200 数据不足、' : ''}信号数据暂缺。</span></div>
  const labels: Record<string, string> = {
    above_ma200: 'QQQ 收盘高于 MA200', qqq_above_ma200: 'QQQ 收盘高于 MA200', stock_above_ma200: row.ma200 == null ? 'MA200 数据不足' : '标的收盘高于 MA200',
    rsi_below_45: 'RSI14 < 45', daily_drop: row.symbol === 'QQQ' ? '当日跌幅 > 1%' : '当日跌幅 > 5%',
    live_quote: '有效实时行情', daily_limit: '当日开仓限频', weekly_limit: '本周开仓限频',
    history: '至少 252 日历史', second_entry: decision?.open_slots.length ? '第二批加仓 RSI14 < 40' : '首批开仓条件', club_member: '策略观察列表标的', next_slot: '可用槽位',
  }
  const entries = Object.entries(signal.checks).filter(([key]) => labels[key])
  const missing = entries.filter(([, value]) => !value).map(([key]) => labels[key])
  const blocked = !missing.length && !signal.eligible
  return <div role="cell" className="leaps-entry-explanation">
    {missing.length > 0 && <span>未满足：{missing.join('、')}。</span>}
    {signal.eligible && !missing.length && <span title="全部入场条件已满足">—</span>}
    {blocked && <span>未满足：开仓额度或槽位。</span>}
  </div>
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
      <div><Building2 size={17} /><span>成员维护</span><strong>手动维护股票列表</strong><small>设置中增删 · 至少 252 个完成交易日</small></div>
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
    {open && quoteDescription(call) && <small className="quote-provenance">{quoteDescription(call)}</small>}
    {open && call.last_error && <small className="quote-provenance error">{call.last_error}</small>}
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
      <div><span>槽位 {position.tranche ?? '—'} · {isEquity ? 'QLD 平替仓' : ADDITIONAL_ETFS.includes(position.symbol) ? 'ETF LEAPS' : isClubPosition(position) ? '万亿俱乐部' : 'QQQ LEAPS'}</span><h3><b className="lot-symbol">{position.symbol}</b>{isEquity ? '正股' : `$${position.strike} Call`} #{position.id}</h3></div>
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
    {quoteDescription(position) && <p className="quote-provenance">{quoteDescription(position)}</p>}
    {position.last_error && <p className="quote-provenance error">{position.last_error}</p>}

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
  if (ADDITIONAL_ETFS.includes(position.symbol)) return false
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
