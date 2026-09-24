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
  RefreshCw,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import { putHasLiveExposure } from './WheelPage'
import type { OtherHolding, OtherHoldingListing, WheelOverview, WheelPutLot, WheelRound } from '../lib/types'
import './WheelPage.css'
import './OtherHoldingsPage.css'

export function OtherHoldingsPage({ listing, wheel, pmccSymbols = [] }: {
  listing: OtherHoldingListing
  wheel?: WheelOverview
  pmccSymbols?: string[]
}) {
  const [tab, setTab] = useState<'open' | 'closed'>('open')
  const pmccSymbolSet = useMemo(() => new Set(pmccSymbols), [pmccSymbols])
  const transitionPuts = useMemo(() => wheel
    ? wheel.rounds.flatMap((round) => round.puts
      .filter(putHasLiveExposure)
      .map((put) => ({ put, round })))
    : [], [wheel])
  const visibleRecords = useMemo(
    () => listing.records.filter((record) => !(isSellCall(record) && isPmccCall(record, pmccSymbolSet))),
    [listing.records, pmccSymbolSet],
  )
  const records = useMemo(
    () => visibleRecords.filter((record) => record.status === tab),
    [visibleRecords, tab],
  )
  const openRecords = visibleRecords.filter((record) => record.status === 'open')
  const openRecordCount = openRecords.length + transitionPuts.length
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

    <div className="segmented-control other-tabs" aria-label="其他持仓视图">
      <button className={tab === 'open' ? 'active' : ''} onClick={() => setTab('open')}><Boxes size={15} />当前持仓 <b>{openRecordCount}</b></button>
      <button className={tab === 'closed' ? 'active' : ''} onClick={() => setTab('closed')}><History size={15} />退出记录 <b>{closedCount}</b></button>
    </div>

    <section className="other-register">
      <header className="section-title">
        <div><p>{tab === 'open' ? 'OPEN POSITIONS' : 'EXIT ARCHIVE'}</p><h2>{tab === 'open' ? '报表当前持仓' : '历史退出记录'}</h2></div>
        <span>{records.length + (tab === 'open' ? transitionPuts.length : 0)} 笔</span>
      </header>
      {records.length || (tab === 'open' && transitionPuts.length) ? <div className="other-table" role="table" aria-label={tab === 'open' ? '当前其他持仓' : '其他持仓退出记录'}>
        <div className="other-row head" role="row">
          <span>分类 / 标的</span><span>方向</span><span>数量</span><span>平均成本</span><span>{tab === 'open' ? '当前价格' : '退出价格'}</span><span>{tab === 'open' ? '当前价值' : '已实现盈亏'}</span><span>{tab === 'open' ? '未实现盈亏' : '退出日期'}</span><span>数据状态</span>
        </div>
        {tab === 'open' && transitionPuts.map(({ put, round }) => <TransitionPutRow key={`wheel-${put.id}`} put={put} round={round} />)}
        {records.map((record) => <HoldingRow key={record.id} record={record} />)}
      </div> : <div className="other-empty"><PackageOpen size={26} /><strong>{tab === 'open' ? '报表中没有策略外持仓' : '尚无退出记录'}</strong></div>}
    </section>
  </div>
}

function TransitionPutRow({ put, round }: { put: WheelPutLot; round: WheelRound }) {
  const currentPrice = put.quote_last ?? put.theoretical_base
  const buybackValue = currentPrice == null ? null : currentPrice * put.open_quantity * 100
  const premiumTotal = put.premium * put.quantity * 100
  const unrealized = buybackValue == null ? null : premiumTotal - buybackValue
  const liveQuantity = put.open_quantity > 0 ? put.open_quantity : put.assigned_contracts
  const status = put.open_quantity > 0 ? '持仓中' : put.share_lots.some((share) => share.state === 'held') ? '已接股' : '管理中'
  const roundCash = roundCashReceived(round)
  return <div className="other-row transition-row" role="row" aria-label={`Wheel 过渡仓 ${put.symbol} Sell Put #${put.id}`}>
    <div className="other-instrument">
      <span className="other-category wheel_transition">Wheel 过渡仓</span>
      <strong>{put.symbol} ${put.strike} Put</strong>
      <small>第 {round.number} 轮 · {put.trade_date} · 到期 {put.expiration}</small>
      <small className="transition-detail">权利金总额 {formatMoney(premiumTotal)} · 当前担保 {formatMoney(put.collateral)} · {status}</small>
      {put.rolled_from && <small className="transition-detail"><RefreshCw size={11} />由 ${put.rolled_from.from_strike} 展期至 ${put.rolled_from.to_strike} · {roundCashLabel(roundCash)} {formatMoney(Math.abs(roundCash))}</small>}
      {put.rolled_to && <small className="transition-detail"><RefreshCw size={11} />已展期至 ${put.rolled_to.to_strike} · {roundCashLabel(roundCash)} {formatMoney(Math.abs(roundCash))}</small>}
    </div>
    <span className="direction short">Short Put</span>
    <strong>{liveQuantity} / {put.quantity} 张</strong>
    <span>{formatMoney(put.premium)}</span>
    <span>{currentPrice == null ? '等待报价' : formatMoney(currentPrice)}</span>
    <strong>{buybackValue == null ? formatMoney(put.collateral) : formatMoney(buybackValue)}</strong>
    <span className={unrealized == null ? '' : unrealized >= 0 ? 'positive' : 'negative'}>{unrealized == null ? '-' : formatMoney(unrealized)}</span>
    <small className="quote-state">{putQuoteLabel(put)}</small>
  </div>
}

function roundCashReceived(round: WheelRound) {
  const realized = round.realized_profit
  const openPutPremium = round.puts.reduce((total, put) => total + put.premium * put.open_quantity * 100, 0)
  const openCallPremium = round.puts.reduce(
    (total, put) => total + put.share_lots.reduce(
      (shareTotal, share) => shareTotal + share.calls.reduce(
        (callTotal, call) => callTotal + (call.state === 'open' ? call.premium * call.quantity * 100 : 0),
        0,
      ),
      0,
    ),
    0,
  )
  return realized + openPutPremium + openCallPremium
}

function roundCashLabel(value: number) { return value >= 0 ? '共收' : '共付' }

function putQuoteLabel(put: WheelPutLot) {
  if (put.quote_source === 'public') return put.quote_as_of ?? '公开报价'
  if (put.quote_source === 'theoretical') return '理论估算'
  return '等待行情刷新'
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
