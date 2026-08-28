import { useState } from 'react'
import { CalendarCheck, Check, RefreshCw, Scale, WalletCards } from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import type { RebalancingSnapshot } from '../lib/types'
import './RebalancingPage.css'

type RebalancingAction = (path: string, payload: unknown, method?: 'POST' | 'PATCH' | 'DELETE') => Promise<void>

const bucketNames = {
  core: '核心仓',
  cash: '现金',
  options: '期权策略共享池',
} as const

export function RebalancingPage({ snapshot, onEvaluate, onAction }: {
  snapshot: RebalancingSnapshot | null
  onEvaluate: (date: string) => Promise<void>
  onAction: RebalancingAction
}) {
  const [evaluationDate, setEvaluationDate] = useState(today())
  const [busy, setBusy] = useState(false)
  if (!snapshot) return <div className="rebalance-empty"><Scale size={24} /><p>账户初始化后可进行再平衡评估</p></div>

  const evaluate = async () => {
    setBusy(true)
    try { await onEvaluate(evaluationDate) } finally { setBusy(false) }
  }
  return <div className="page-stack rebalance-console">
    <div className="page-heading"><div><p className="eyebrow">ACCOUNT REBALANCING</p><h1>账户再平衡</h1></div><span>只生成建议，券商成交后再记账</span></div>

    <section className={`rebalance-schedule ${snapshot.schedule.due ? 'due' : ''}`}>
      <div className="rebalance-status"><CalendarCheck size={21} /><div><span>六个月复核</span><strong>{snapshot.schedule.due ? '本期复核已到期' : '尚未到复核日'}</strong><small>下次复核 {snapshot.schedule.next_review_on}</small></div></div>
      <label>评估日期<input type="date" value={evaluationDate} onChange={(event) => setEvaluationDate(event.target.value)} /></label>
      <button className="secondary-button" disabled={busy} onClick={() => void evaluate()}><RefreshCw size={15} />按当前日期评估</button>
      <button className="secondary-button" onClick={() => void onAction('/rebalancing/confirm-no-trade', { date: snapshot.as_of }, 'POST')}><Check size={15} />本期无需交易</button>
    </section>

    <section className="rebalance-allocation">
      <div className="section-title"><div><p>MARK-TO-MARKET</p><h2>经济权益</h2></div><span>合计 {formatMoney(snapshot.economic.total)}</span></div>
      <div className="rebalance-allocation-grid">
        {(Object.keys(bucketNames) as Array<keyof typeof bucketNames>).map((bucket) => {
          const row = snapshot.economic.buckets[bucket]
          return <div key={bucket}><span>{bucketNames[bucket]}</span><strong>{formatMoney(row.value)}</strong><small>经济 {(row.fraction * 100).toFixed(1)}% · 目标 {(row.target_fraction * 100).toFixed(1)}%</small><em className={row.deviation >= 0 ? 'over' : 'under'}>{bucketNames[bucket]} {formatPoints(row.deviation)}</em></div>
        })}
      </div>
    </section>

    <section className="rebalance-decision">
      <div><p className="eyebrow">CORE BANDS</p><h2>{coreDecisionLabel(snapshot.core_decision.code)}</h2><span>核心仓当前偏离 {formatPoints(snapshot.economic.buckets.core.deviation)}</span></div>
      <div><span>目标缓冲线</span><strong>{(snapshot.core_decision.target_after_sale * 100).toFixed(1)}%</strong><small>建议卖出至目标 +5 个百分点</small></div>
      <div><span>估算卖出金额</span><strong>{formatMoney(snapshot.core_decision.sell_amount)}</strong><small>{snapshot.core_decision.symbol} 约 {snapshot.core_decision.estimated_shares.toFixed(4)} 股</small></div>
    </section>

    <section className="rebalance-recommendations">
      <div className="section-title"><div><p>PRIORITY QUEUE</p><h2>只读执行顺序</h2></div><span>{snapshot.recommendations.length} 项建议</span></div>
      {snapshot.recommendations.length ? <div className="recommendation-list">{snapshot.recommendations.map((item) => <div key={`${item.priority}-${item.code}`}><b>{item.priority}</b><span><strong>{recommendationLabel(item.code)}</strong><small>{item.message}</small></span><em>{formatMoney(item.amount)}</em></div>)}</div> : <div className="rebalance-clear"><Check size={18} />当前没有需要执行的资金调整</div>}
    </section>

    <section className="rebalance-locked"><WalletCards size={19} /><div><strong>{snapshot.core_decision.actionable ? '核心仓出现再平衡卖出建议' : '当前无需执行核心仓卖出'}</strong><span>券商成交结果由下一份 IBKR 报表同步，页面不提供手工成交录入。</span></div></section>
  </div>
}

function coreDecisionLabel(code: RebalancingSnapshot['core_decision']['code']) {
  return { underweight: '核心仓低于目标', pause: '暂停加速买入', observe: '观察区，优先补其他桶', sell: '核心仓达到再平衡卖出区' }[code]
}
function recommendationLabel(code: string) {
  if (code === 'eliminate_margin') return '消除 Margin 缺口'
  if (code === 'restore_cash') return '恢复目标现金'
  if (code === 'replenish_options') return '补足期权策略共享池'
  if (code === 'sell_core') return '降低核心仓超配'
  return code
}
function formatPoints(value: number) { return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)} 个百分点` }
function today() { return new Date().toISOString().slice(0, 10) }
