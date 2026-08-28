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
  TrendingDown,
  TrendingUp,
} from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import type { OtherHolding, OtherHoldingListing } from '../lib/types'
import './OtherHoldingsPage.css'

export function OtherHoldingsPage({ listing }: {
  listing: OtherHoldingListing
}) {
  const [tab, setTab] = useState<'open' | 'closed'>('open')
  const records = useMemo(
    () => listing.records.filter((record) => record.status === tab),
    [listing.records, tab],
  )
  const openRecords = listing.records.filter((record) => record.status === 'open')
  const floatingProfit = openRecords.reduce((total, record) => total + (record.unrealized_profit ?? 0), 0)
  const closedCount = listing.records.length - openRecords.length

  return <div className="page-stack other-page">
    <div className="page-heading">
      <div><p className="eyebrow">BROKER OUTSIDE BOOK</p><h1>其他持仓</h1></div>
      <span>由 IBKR 报表同步 · 不占策略桶</span>
    </div>

    <section className="other-summary" aria-label="其他持仓汇总">
      <SummaryMetric icon={<Banknote size={18} />} label="BOXX 现金等价物" value={listing.cash_equivalent_value} note="计入现金类，不视为可直接动用" tone="cash" />
      <SummaryMetric icon={<Layers3 size={18} />} label="其他持仓净值" value={listing.other_value} note={`${openRecords.filter((record) => record.category === 'other').length} 笔待退出持仓`} />
      <SummaryMetric icon={floatingProfit >= 0 ? <TrendingUp size={18} /> : <TrendingDown size={18} />} label="未实现盈亏" value={floatingProfit} note="按报表价或最近一次行情" tone={floatingProfit >= 0 ? 'positive' : 'negative'} />
      <SummaryMetric icon={<Archive size={18} />} label="退出记录" value={closedCount} note={listing.unpriced_count ? `${listing.unpriced_count} 笔暂无有效报价` : '当前持仓均有估值'} count />
    </section>

    <section className="other-policy-band">
      <div><CircleDollarSign size={19} /><span><strong>现金分类</strong><small>BOXX 市值包含在现金桶本金内，但卖出前不会增加可用现金。</small></span></div>
      <div><FileInput size={19} /><span><strong>报表为准</strong><small>新增、数量、成本与持仓状态通过 IBKR 导入对账。</small></span></div>
    </section>

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
