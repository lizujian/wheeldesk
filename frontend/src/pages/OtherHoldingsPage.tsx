import { useMemo, useState } from 'react'
import {
  Archive,
  Banknote,
  Boxes,
  CircleDollarSign,
  FileInput,
  History,
  Layers3,
  PackageOpen,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Waypoints,
} from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import { BudgetBand, PutLot, putHasLiveExposure } from './WheelPage'
import type { OtherHolding, OtherHoldingListing, WheelOverview } from '../lib/types'
import './WheelPage.css'
import './OtherHoldingsPage.css'

export function OtherHoldingsPage({ listing, wheel, pmccSymbols = [] }: {
  listing: OtherHoldingListing
  wheel?: WheelOverview
  pmccSymbols?: string[]
}) {
  const [tab, setTab] = useState<'open' | 'closed'>('open')
  const pmccSymbolSet = useMemo(() => new Set(pmccSymbols), [pmccSymbols])
  const transitionCalls = useMemo(() => {
    const calls = listing.records.filter((record) => isSellCall(record) && !isPmccCall(record, pmccSymbolSet))
    return [...new Map(calls.map((call) => [call.id, call])).values()]
  }, [listing.records, pmccSymbolSet])
  const visibleRecords = useMemo(
    () => listing.records.filter((record) => !(isSellCall(record) && isPmccCall(record, pmccSymbolSet))),
    [listing.records, pmccSymbolSet],
  )
  const records = useMemo(
    () => visibleRecords.filter((record) => record.status === tab),
    [visibleRecords, tab],
  )
  const openRecords = visibleRecords.filter((record) => record.status === 'open')
  const floatingProfit = openRecords.reduce((total, record) => total + (record.unrealized_profit ?? 0), 0)
  const otherValue = openRecords.reduce((total, record) => total + (record.category === 'other' ? record.current_value ?? 0 : 0), 0)
  const closedCount = visibleRecords.length - openRecords.length

  return <div className="page-stack other-page">
    <div className="page-heading">
      <div><p className="eyebrow">BROKER OUTSIDE BOOK</p><h1>其他持仓与过渡仓</h1></div>
      <span>由 IBKR 报表同步 · Wheel 只做持仓管理</span>
    </div>

    <section className="other-summary" aria-label="其他持仓汇总">
      <SummaryMetric icon={<Banknote size={18} />} label="BOXX 现金等价物" value={listing.cash_equivalent_value} note="计入现金桶，可参与资金分配" tone="cash" />
      <SummaryMetric icon={<Layers3 size={18} />} label="其他持仓净值" value={otherValue} note={`${openRecords.filter((record) => record.category === 'other').length} 笔待退出持仓`} />
      <SummaryMetric icon={floatingProfit >= 0 ? <TrendingUp size={18} /> : <TrendingDown size={18} />} label="未实现盈亏" value={floatingProfit} note="按报表价或最近一次行情" tone={floatingProfit >= 0 ? 'positive' : 'negative'} />
      <SummaryMetric icon={<Archive size={18} />} label="退出记录" value={closedCount} note={listing.unpriced_count ? `${listing.unpriced_count} 笔暂无有效报价` : '当前持仓均有估值'} count />
    </section>

    <section className="other-policy-band">
      <div><CircleDollarSign size={19} /><span><strong>现金分类</strong><small>BOXX 市值包含在现金桶本金内，但卖出前不会增加可用现金。</small></span></div>
      <div><FileInput size={19} /><span><strong>报表为准</strong><small>新增、数量、成本与持仓状态通过 IBKR 导入对账。</small></span></div>
    </section>

    {wheel && <WheelTransitionSection wheel={wheel} callWheels={transitionCalls} />}

    <div className="segmented-control other-tabs" aria-label="其他持仓视图">
      <button className={tab === 'open' ? 'active' : ''} onClick={() => setTab('open')}><Boxes size={15} />当前持仓 <b>{openRecords.length}</b></button>
      <button className={tab === 'closed' ? 'active' : ''} onClick={() => setTab('closed')}><History size={15} />退出记录 <b>{closedCount}</b></button>
    </div>

    <section className="other-register">
      <header className="section-title">
        <div><p>{tab === 'open' ? 'OPEN POSITIONS' : 'EXIT ARCHIVE'}</p><h2>{tab === 'open' ? '报表当前持仓' : '历史退出记录'}</h2></div>
        <span>{records.length} 笔</span>
      </header>
      {records.length ? <div className="other-table" role="table" aria-label={tab === 'open' ? '当前其他持仓' : '其他持仓退出记录'}>
        <div className="other-row head" role="row">
          <span>分类 / 标的</span><span>方向</span><span>数量</span><span>平均成本</span><span>{tab === 'open' ? '当前价格' : '退出价格'}</span><span>{tab === 'open' ? '当前价值' : '已实现盈亏'}</span><span>{tab === 'open' ? '未实现盈亏' : '退出日期'}</span><span>数据状态</span>
        </div>
        {records.map((record) => <HoldingRow key={record.id} record={record} />)}
      </div> : <div className="other-empty"><PackageOpen size={26} /><strong>{tab === 'open' ? '报表中没有策略外持仓' : '尚无退出记录'}</strong></div>}
    </section>
  </div>
}

function WheelTransitionSection({ wheel, callWheels }: { wheel: WheelOverview; callWheels: OtherHolding[] }) {
  const activeRounds = [...wheel.rounds].reverse().map((round) => ({
    ...round,
    puts: round.puts.filter(putHasLiveExposure),
  })).filter((round) => round.puts.length > 0)
  const activeCalls = callWheels.filter((call) => call.status === 'open')
  const livePutCount = activeRounds.reduce((total, round) => total + round.puts.length, 0)
  const activeCallContracts = activeCalls.reduce((total, call) => total + call.quantity, 0)
  const symbols = [...new Set([
    ...activeRounds.flatMap((round) => round.puts.map((put) => put.symbol)),
    ...callWheels.map((call) => call.symbol),
  ])].sort()
  const clusters = symbols.map((symbol) => ({
    symbol,
    rounds: activeRounds.map((round) => ({ ...round, puts: round.puts.filter((put) => put.symbol === symbol) })).filter((round) => round.puts.length > 0),
    calls: callWheels.filter((call) => call.symbol === symbol),
  }))

  return <section className="wheel-transition" aria-label="Wheel 过渡仓">
    <header className="wheel-transition-header">
      <div><p>TRANSITION BOOK</p><h2>Wheel 过渡仓</h2><span>按标的聚类管理已有 Sell Put、展期、接股与 Sell Call，不再扩张仓位</span></div>
      <div className="wheel-transition-status"><Waypoints size={17} /><strong>只管理，不扩张</strong><small>不生成新的 Wheel 开仓信号</small></div>
    </header>

    <BudgetBand overview={wheel} />

    <div className="wheel-transition-note"><ShieldCheck size={16} /><span>Wheel 不再参与新开仓信号；已有仓位仍按原规则结算。当前台账只管理 Wheel Put 链与普通 Sell Call。</span></div>

    <section className="wheel-register transition-register" aria-label="Wheel 个股策略台账">
      <div className="section-title">
        <div><p>LIVE TRANSITION REGISTER</p><h2>按标的管理</h2></div>
        <span>{symbols.length} 个标的 · {livePutCount} 笔 Sell Put · {activeCallContracts} 张活动 Sell Call · 累计已实现 {formatMoney(wheel.realized_profit)}</span>
      </div>
      {clusters.length === 0
        ? <div className="wheel-empty"><CircleDollarSign size={22} /><div><p>当前没有需要管理的 Wheel / Sell Call 仓位</p><small>历史记录仍保留在账本中。</small></div></div>
        : <div className="wheel-transition-clusters">{clusters.map((cluster) => <TransitionCluster key={cluster.symbol} {...cluster} />)}</div>}
    </section>

    <footer><ShieldCheck size={15} /><span>AVGO Sell Put 与其展期链路保留在 Wheel 过渡仓；普通 Sell Call 仍按 IBKR 报表更新。</span></footer>
  </section>
}

function TransitionCluster({ symbol, rounds, calls }: {
  symbol: string
  rounds: Array<WheelOverview['rounds'][number]>
  calls: OtherHolding[]
}) {
  const activeCalls = calls.filter((call) => call.status === 'open')
  const historyCalls = calls.filter((call) => call.status !== 'open')
  const putCount = rounds.reduce((total, round) => total + round.puts.length, 0)
  const callContracts = activeCalls.reduce((total, call) => total + call.quantity, 0)
  return <article className="wheel-transition-cluster" aria-label={`${symbol} 个股策略簇`}>
    <header>
      <div><span>INDIVIDUAL STRATEGY CLUSTER</span><h3>{symbol}</h3></div>
      <div className="wheel-transition-cluster-summary"><strong>{putCount ? `${putCount} 笔 Sell Put` : '无 Sell Put'}</strong><strong>{callContracts ? `${callContracts} 张活动 Sell Call` : '无活动 Sell Call'}</strong></div>
    </header>
    <div className="wheel-transition-cluster-body">
      {rounds.map((round) => <section className={`wheel-round ${round.status}`} key={round.id}>
        <header><div><span>第 {round.number} 轮</span><strong>{round.status === 'active' ? '进行中' : '持仓链路'}</strong></div><div><small>{round.opened_on}{round.closed_on ? ` 至 ${round.closed_on}` : ''}</small><b>{formatMoney(round.realized_profit)}</b></div></header>
        <div className="wheel-lots">{round.puts.map((put) => <PutLot key={put.id} put={put} roundNumber={round.number} />)}</div>
      </section>)}
      {calls.length > 0 && <section className="wheel-transition-short-calls" aria-label={`${symbol} Sell Call 台账`}>
        <header><div><p>SELL CALL CASH FLOW</p><h4>Sell Call</h4></div><span>{activeCalls.length} 笔活动{historyCalls.length ? ` · ${historyCalls.length} 笔历史` : ''}</span></header>
        {activeCalls.map((call) => <TransitionShortCall key={call.id} call={call} />)}
        {historyCalls.length > 0 && <details><summary>查看已平仓 Sell Call（{historyCalls.length} 笔）</summary>{historyCalls.map((call) => <TransitionShortCall key={call.id} call={call} />)}</details>}
      </section>}
    </div>
  </article>
}

function TransitionShortCall({ call }: { call: OtherHolding }) {
  const open = call.status === 'open'
  const buybackPrice = open ? call.current_price : call.exit_price
  const buybackValue = buybackPrice == null ? null : Math.abs(buybackPrice * call.quantity * call.multiplier)
  const premiumTotal = (call.entry_price ?? 0) * call.quantity * call.multiplier
  const netCashFlow = call.pmcc_state?.net_cash_flow ?? (buybackValue == null ? null : premiumTotal - buybackValue)
  const status = open ? shortCallStatus(call.pmcc_state?.status) : call.status === 'closed' ? '已平仓' : '已结束'
  return <article className={`wheel-transition-call-card ${netCashFlow != null && netCashFlow < 0 ? 'loss' : ''}`} aria-label={`${call.symbol} Sell Call #${call.id}`}>
    <div className="wheel-transition-call-title"><b>{call.symbol}</b><strong>{formatMoney(call.strike ?? 0)} Call</strong><span>{status}</span></div>
    <div><small>合约</small><strong>{call.quantity} 张</strong></div>
    <div><small>权利金 / 股</small><strong>{formatMoney(call.entry_price ?? 0)}</strong></div>
    <div><small>权利金总额</small><strong>{formatMoney(premiumTotal)}</strong></div>
    <div><small>{open ? '当前买回价' : '退出价格'}</small><strong>{buybackPrice == null ? '等待报价' : formatMoney(buybackPrice)}</strong></div>
    <div><small>{open ? '净现金流' : '已实现盈亏'}</small><strong>{open ? netCashFlow == null ? '等待报价' : formatMoney(netCashFlow) : formatMoney(call.realized_profit ?? 0)}</strong></div>
    <div><small>到期日</small><strong>{call.expiration ?? '—'}</strong></div>
    {call.linked_position_id && <small className="wheel-transition-call-link">关联 Long Call #{call.linked_position_id} · 覆盖 {call.pmcc_state ? `${(call.pmcc_state.coverage_ratio * 100).toFixed(0)}%` : '待核对'}</small>}
    {call.pmcc_state && <small className="wheel-transition-call-link">最大损失 {formatMoney(call.pmcc_state.maximum_loss)} · Short DTE {call.pmcc_state.short_dte ?? '—'}{call.pmcc_state.assignment_risk ? ' · 行权风险' : ''}</small>}
  </article>
}

function shortCallStatus(status?: NonNullable<OtherHolding['pmcc_state']>['status']) {
  if (status === 'covered') return '已覆盖'
  if (status === 'needs_roll') return '进入展期窗口'
  if (status === 'assignment_risk') return '行权风险'
  if (status === 'expired') return '已到期'
  return '未覆盖 / 待核对'
}

function isSellCall(record: OtherHolding) {
  return record.asset_type === 'option' && record.direction === 'short' && record.option_type === 'call'
}

function isPmccCall(record: OtherHolding, pmccSymbols: ReadonlySet<string>) {
  if (!isSellCall(record)) return false
  return record.category === 'leaps_call_wheel' || record.category === 'pmcc' || record.linked_position_id != null || pmccSymbols.has(record.symbol)
}

function HoldingRow({ record }: { record: OtherHolding }) {
  const isOpen = record.status === 'open'
  const result = isOpen ? record.unrealized_profit : record.realized_profit
  return <div className="other-row" role="row" aria-label={contractLabel(record)}>
    <div className="other-instrument">
      <span className={`other-category ${record.category}`}>{record.category === 'cash_equivalent' ? '现金等价' : '其他'}</span>
      <strong>{contractLabel(record)}</strong>
      <small>{record.opened_on ?? '开仓日期未知'}{record.expiration ? ` · 到期 ${record.expiration}` : ''}</small>
    </div>
    <span className={`direction ${record.direction}`}>{directionLabel(record)}</span>
    <strong>{formatQuantity(record)}</strong>
    <span>{nullableMoney(record.entry_price)}</span>
    <span>{nullableMoney(isOpen ? record.current_price : record.exit_price)}</span>
    <strong>{nullableMoney(isOpen ? record.current_value : record.realized_profit)}</strong>
    <span className={result === null ? '' : result >= 0 ? 'positive' : 'negative'}>{isOpen ? nullableMoney(result) : record.closed_on ?? '-'}</span>
    <small className={`quote-state ${record.quote_status}`}>{isOpen ? quoteLabel(record) : '已退出'}</small>
  </div>
}

function SummaryMetric({ icon, label, value, note, tone = '', count = false }: {
  icon: React.ReactNode
  label: string
  value: number
  note: string
  tone?: string
  count?: boolean
}) {
  return <div className={tone}>{icon}<span>{label}</span><strong>{count ? value : formatMoney(value)}</strong><small>{note}</small></div>
}

function contractLabel(record: OtherHolding) {
  if (record.asset_type === 'equity') return record.symbol
  const right = record.option_type === 'call' ? 'Call' : 'Put'
  return `${record.symbol} ${record.expiration ?? '-'} $${record.strike ?? '-'} ${right}`
}

function directionLabel(record: OtherHolding) {
  if (record.asset_type === 'equity') return 'Long Stock'
  return `${record.direction === 'long' ? 'Long' : 'Short'} ${record.option_type === 'call' ? 'Call' : 'Put'}`
}

function formatQuantity(record: OtherHolding) {
  return `${record.direction === 'short' ? '-' : ''}${record.quantity.toLocaleString('en-US', { maximumFractionDigits: 4 })} ${record.asset_type === 'option' ? '张' : '股'}`
}

function nullableMoney(value: number | null) { return value === null ? '-' : formatMoney(value) }

function quoteLabel(record: OtherHolding) {
  if (record.quote_status === 'updated') return record.quote_as_of ?? '已更新'
  return record.quote_status === 'stale' ? '本次刷新未更新' : '暂无有效报价'
}
