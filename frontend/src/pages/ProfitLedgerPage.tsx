import { FormEvent, useEffect, useMemo, useState } from 'react'
import { ArrowRight, CircleDollarSign, HandCoins, LockKeyhole, ReceiptText, TrendingDown, TrendingUp } from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import type { DistributionRecommendation, ProfitLedgerEntry, ProfitLedgerSnapshot } from '../lib/types'
import './ProfitLedgerPage.css'

type ProfitAction = (path: string, payload: unknown) => Promise<void>
type RedistributionAction = (amount: number) => Promise<DistributionRecommendation | void>

const bucketLabels: Record<string, string> = { core: '核心仓', cash: '现金储备', wheel: '期权策略共享池', leaps: '期权策略共享池' }
const sourceLabels: Record<string, string> = { wheel: 'TQQQ 车轮', leaps: 'QQQ LEAPS', other: '其他已实现', allocation: '已确认分配' }

export function ProfitLedgerPage({ ledger, onAction, onRedistribute }: {
  ledger: ProfitLedgerSnapshot
  onAction: ProfitAction
  onRedistribute: RedistributionAction
}) {
  const [plannedAmount, setPlannedAmount] = useState(String(ledger.summary.available || ''))
  const [recommendation, setRecommendation] = useState<DistributionRecommendation | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setPlannedAmount(String(ledger.summary.available || '')); setRecommendation(null) }, [ledger.summary.available])
  const confirmedAmount = useMemo(() => recommendation
    ? Object.values(recommendation.allocations).reduce((total, amount) => total + amount, 0)
    : 0, [recommendation])

  const generate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const amount = Number(plannedAmount)
    if (amount <= 0 || amount > ledger.summary.available) return
    setRecommendation((await onRedistribute(amount)) ?? null)
  }
  const confirmAllocation = async () => {
    if (!recommendation || confirmedAmount <= 0) return
    setBusy(true)
    try {
      await onAction('/profit-ledger/allocations', {
        occurred_on: today(),
        amount: confirmedAmount,
        allocations: recommendation.allocations,
        note: '按目标缺口确认分配',
      })
      setRecommendation(null)
    } finally { setBusy(false) }
  }

  return <div className="page-stack profit-console">
    <div className="page-heading"><div><p className="eyebrow">DISTRIBUTABLE PROFIT</p><h1>可分配收益流水</h1></div><span>{ledger.entries.length} 条流水</span></div>
    <section className="profit-metrics" aria-label="可分配收益汇总">
      <ProfitMetric icon={<HandCoins size={18} />} label="当前可分配" value={ledger.summary.available} accent />
      <ProfitMetric icon={<ReceiptText size={18} />} label="车轮已实现" value={ledger.summary.wheel_realized} />
      <ProfitMetric icon={<TrendingUp size={18} />} label="LEAPS 已实现" value={ledger.summary.leaps_realized} />
      <ProfitMetric icon={<CircleDollarSign size={18} />} label="其他已实现" value={ledger.summary.other_realized} />
      <ProfitMetric icon={<TrendingDown size={18} />} label="已确认分配" value={ledger.summary.allocated} />
    </section>
    <div className="profit-workbench">
      <section className="profit-allocation-panel">
        <div className="section-title"><div><p>TARGET GAP</p><h2>收益再分配</h2></div><ArrowRight size={20} /></div>
        <form aria-label="生成收益再分配建议" className="profit-allocation-form" onSubmit={generate}>
          <label>本次计划分配<input type="number" min="0.01" max={ledger.summary.available} step="0.01" value={plannedAmount} onChange={(event) => setPlannedAmount(event.target.value)} required /></label>
          <button className="secondary-button" disabled={ledger.summary.available <= 0}>生成缺口建议</button>
        </form>
        {recommendation && <div className="profit-recommendation">
          <div className="recommendation-grid">{Object.entries(recommendation.allocations).filter(([, amount]) => amount > 0).map(([bucket, amount]) => <div key={bucket}><span>{bucketLabels[bucket]}</span><strong>{formatMoney(amount)}</strong></div>)}</div>
          {recommendation.unallocated > 0 && <div className="recommendation-unallocated"><span>暂不分配</span><strong>{formatMoney(recommendation.unallocated)}</strong></div>}
          <button className="primary-button" onClick={confirmAllocation} disabled={busy || confirmedAmount <= 0}>{busy ? '正在确认...' : '确认本次已分配'}</button>
        </div>}
      </section>
    </div>
    <section className="profit-register">
      <div className="section-title"><div><p>PROFIT REGISTER</p><h2>已实现与分配流水</h2></div><span>净已实现 {formatMoney(ledger.summary.net_realized)}</span></div>
      {ledger.entries.length ? <div className="profit-table">
        <div className="profit-row header"><span>日期</span><span>来源</span><span>说明</span><span>分配明细</span><span>金额</span><span>状态</span></div>
        {ledger.entries.map((entry) => <ProfitRow key={entry.id} entry={entry} />)}
      </div> : <div className="empty-state"><ReceiptText size={22} /><p>尚无可分配收益流水</p></div>}
    </section>
  </div>
}

function ProfitRow({ entry }: { entry: ProfitLedgerEntry }) {
  const detail = Object.entries(entry.allocations).filter(([, amount]) => Number(amount) > 0).map(([bucket, amount]) => `${bucketLabels[bucket]} ${formatMoney(Number(amount))}`).join(' · ')
  return <div className={`profit-row ${entry.entry_type}`}>
    <span>{entry.occurred_on}</span>
    <strong>{sourceLabels[entry.source]}{entry.automatic && <em>自动</em>}</strong>
    <span>{entry.note || '—'}</span>
    <small>{detail || '—'}</small>
    <b className={entry.amount >= 0 ? 'positive' : 'negative'}>{entry.amount > 0 ? '+' : ''}{formatMoney(entry.amount)}</b>
    <div><span title="流水由券商报表或系统结算产生"><LockKeyhole size={15} aria-label="只读流水" /></span></div>
  </div>
}

function ProfitMetric({ icon, label, value, accent = false }: { icon: React.ReactNode; label: string; value: number; accent?: boolean }) {
  return <div className={accent ? 'accent' : ''}>{icon}<span>{label}</span><strong className={value < 0 ? 'negative' : ''}>{formatMoney(value)}</strong></div>
}

function today() { return new Date().toISOString().slice(0, 10) }
