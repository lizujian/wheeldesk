import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  BellRing,
  Check,
  CheckCircle2,
  Clock3,
  Radio,
} from 'lucide-react'
import { Link } from 'react-router-dom'

import type { Signal } from '../lib/types'
import './SignalsPage.css'

const severityIcon = { critical: AlertCircle, warning: AlertTriangle, opportunity: BellRing, info: Radio }
const severityLabel = { critical: '高危', warning: '警告', opportunity: '机会', info: '信息' }

export function SignalsPage({ signals, onAcknowledge }: { signals: Signal[]; onAcknowledge: (id: number) => Promise<void> }) {
  const active = signals.filter((signal) => !signal.acknowledged)
  const history = signals.filter((signal) => signal.acknowledged)
  const primary = active[0] ?? null
  const remaining = active.slice(1)
  const criticalCount = active.filter((signal) => signal.severity === 'critical').length
  const opportunityCount = active.filter((signal) => signal.severity === 'opportunity').length

  return <div className="page-stack signals-console">
    <div className="page-heading">
      <div><p className="eyebrow">ACTION SIGNALS</p><h1>信号中心</h1><span>系统建议，用户确认后在 IBKR 执行</span></div>
      <span>{active.length} 条待处理 · {history.length} 条近期记录</span>
    </div>

    <section className="signal-status-strip" aria-label="信号概览">
      <SignalCount label="待处理" value={active.length} note={active.length ? '需要查看或确认' : '当前队列已清空'} active={active.length > 0} />
      <SignalCount label="高危风控" value={criticalCount} note={criticalCount ? '优先于所有机会信号' : '当前无高危信号'} danger={criticalCount > 0} />
      <SignalCount label="开仓机会" value={opportunityCount} note={opportunityCount ? '按交易日与策略排序' : '等待下一次行情刷新'} />
    </section>

    {primary ? <PrimarySignal signal={primary} onAcknowledge={onAcknowledge} /> : <section className="signal-clear-state" aria-label="无待处理信号">
      <CheckCircle2 size={24} />
      <div><span>CLEAR</span><strong>当前没有待处理信号</strong><small>已处理或条件变化的建议保留在下方近期记录。</small></div>
    </section>}

    {remaining.length > 0 && <section className="signal-queue" aria-labelledby="signal-queue-title">
      <header><div><p>ACTIVE QUEUE</p><h2 id="signal-queue-title">其余待处理</h2></div><span>{remaining.length} 条</span></header>
      <div>{remaining.map((signal) => <QueueSignal signal={signal} onAcknowledge={onAcknowledge} key={signal.id} />)}</div>
    </section>}

    <section className="signal-history" aria-labelledby="signal-history-title">
      <header><div><p>RECENT HISTORY</p><h2 id="signal-history-title">近期归档记录</h2></div><span>已处理或条件变化，仅移出全局提醒</span></header>
      {history.length ? <div className="signal-history-list">{history.map((signal) => <HistorySignal signal={signal} key={signal.id} />)}</div> : <div className="empty-state"><Clock3 size={21} /><p>暂无归档记录</p></div>}
    </section>
  </div>
}

function PrimarySignal({ signal, onAcknowledge }: { signal: Signal; onAcknowledge: (id: number) => Promise<void> }) {
  const Icon = severityIcon[signal.severity]
  const meta = signalMeta(signal.code)
  return <section className={`primary-signal ${signal.severity}`} aria-label="当前最优先信号">
    <div className="primary-signal-mark"><Icon size={25} /><span>{severityLabel[signal.severity]}</span></div>
    <div className="primary-signal-copy">
      <header><span>当前最优先 · {meta.label}</span><time>{signal.market_date}</time></header>
      <h2>{signal.title}</h2>
      <p>{signal.message}</p>
    </div>
    <div className="primary-signal-actions">
      <Link to={meta.path}>查看{meta.label}<ArrowRight size={15} /></Link>
      <button type="button" onClick={() => void onAcknowledge(signal.id)}><Check size={15} />标记为已处理</button>
    </div>
  </section>
}

function QueueSignal({ signal, onAcknowledge }: { signal: Signal; onAcknowledge: (id: number) => Promise<void> }) {
  const Icon = severityIcon[signal.severity]
  const meta = signalMeta(signal.code)
  return <article className={`queue-signal ${signal.severity}`}>
    <Icon size={19} />
    <div><header><span>{severityLabel[signal.severity]} · {meta.label}</span><time>{signal.market_date}</time></header><h3>{signal.title}</h3><p>{signal.message}</p></div>
    <Link to={meta.path} title={`查看${meta.label}`}><ArrowRight size={17} /></Link>
    <button type="button" title="标记为已处理" aria-label={`标记 ${signal.title} 为已处理`} onClick={() => void onAcknowledge(signal.id)}><Check size={17} /></button>
  </article>
}

function HistorySignal({ signal }: { signal: Signal }) {
  const meta = signalMeta(signal.code)
  return <article>
    <CheckCircle2 size={17} />
    <div><span>{meta.label} · {signal.market_date}</span><strong>{signal.title}</strong><small>{signal.message}</small></div>
    <em>已归档</em>
    <Link to={meta.path} title={`查看${meta.label}`}><ArrowRight size={16} /></Link>
  </article>
}

function SignalCount({ label, value, note, active = false, danger = false }: { label: string; value: number; note: string; active?: boolean; danger?: boolean }) {
  return <div className={`${active ? 'active' : ''} ${danger ? 'danger' : ''}`}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>
}

function signalMeta(code: string) {
  if (code.startsWith('core_')) return { label: '核心仓', path: '/core' }
  if (code.includes('wheel') || code.startsWith('sell_put')) return { label: '车轮策略', path: '/wheel' }
  if (code.includes('leaps') || code.startsWith('trillion_club_')) return { label: 'LEAPS', path: '/leaps' }
  if (code === 'vix_high') return { label: '现金储备', path: '/' }
  return { label: '风险监控', path: '/signals' }
}
