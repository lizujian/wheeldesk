import { FormEvent, useMemo, useState } from 'react'
import { ArrowRight, Banknote, CircleDollarSign, Landmark, ShieldAlert, TrendingUp, WalletCards } from 'lucide-react'
import { Link } from 'react-router-dom'
import { AllocationChart, formatMoney } from '../components/AllocationChart'
import type { PortfolioSummary, ProfitLedgerSummary } from '../lib/types'
import './OverviewPage.css'

const rows = [
  ['core', 'BRK.B 核心仓', '长期底仓', '#276a9b'],
  ['cash', '现金储备', '极端行情备用', '#d39b2c'],
  ['options', '期权策略共享池', '车轮与 LEAPS 共用额度', '#138369'],
] as const

export function OverviewPage({ portfolio, profitSummary, onInitialize, onAction = async () => {} }: {
  portfolio: PortfolioSummary
  profitSummary: ProfitLedgerSummary
  onInitialize: (payload: unknown) => Promise<void>
  onAction?: (path: string, payload: unknown, method?: 'POST' | 'PATCH' | 'DELETE') => Promise<void>
}) {
  if (!portfolio.initialized) return <Onboarding onInitialize={onInitialize} />
  const total = portfolio.total_equity ?? 0
  const cash = portfolio.capital?.cash ?? {
    total: portfolio.balances?.cash ?? 0, cash_equivalent: 0, liquid: portfolio.balances?.cash ?? 0,
    occupied: 0,
    available: portfolio.balances?.cash ?? 0,
    margin_shortfall: 0,
  }
  return (
    <div className="page-stack">
      <div className="page-heading"><div><p className="eyebrow">PORTFOLIO CONTROL</p><h1>资产总览</h1></div><span>年龄 {portfolio.age} · 目标按实时权益计算</span></div>
      <section className="metrics-strip three">
        <Metric icon={WalletCards} label="总资产" value={formatMoney(total)} />
        <Metric icon={Landmark} label="净入金" value={formatMoney(portfolio.net_external_capital ?? 0)} />
        <Metric icon={TrendingUp} label="投资损益" value={formatMoney(portfolio.investment_profit ?? 0)} tone={(portfolio.investment_profit ?? 0) >= 0 ? 'positive' : 'negative'} />
      </section>
      <CashControl portfolio={portfolio} />
      <section className="dashboard-band">
        <div className="allocation-panel"><div className="section-title"><div><p>实时配比</p><h2>资金分布</h2></div><span>目标 vs 实际</span></div><AllocationChart portfolio={portfolio} /></div>
        <div className="allocation-table-wrap">
          <div className="section-title"><div><p>DEPLOYMENT GAP</p><h2>目标缺口</h2></div><span>实际部署</span></div>
          <div className="allocation-table">
            {rows.map(([key, name, note, color]) => {
              const target = portfolio.targets?.[key]
              if (!target) return null
              const actual = portfolio.deployments?.[key] ?? target.actual
              const variance = actual - target.amount
              return <div className="allocation-row" key={key}>
                <span className="asset-swatch" style={{ background: color }} />
                <div><strong>{name}</strong><small>{note}</small></div>
                <div className="money-column"><strong>{formatMoney(actual)}</strong><small>目标 {formatMoney(target.amount)}</small></div>
                <span className={`variance ${variance < 0 ? 'under' : variance > 0 ? 'over' : 'balanced'}`}>
                  {variance < 0 ? `低配 ${formatMoney(Math.abs(variance))}` : variance > 0 ? `超配 ${formatMoney(variance)}` : '已达目标'}
                </span>
              </div>
            })}
          </div>
        </div>
      </section>
      <CashTransfer onAction={onAction} cash={cash.available} totalCash={cash.total} />
      <section className="distribution-band">
        <div><p className="eyebrow">DISTRIBUTABLE PROFIT</p><h2>当前可分配收益</h2><p>车轮与 LEAPS 已实现盈亏，扣除已确认分配。</p></div>
        <div className="overview-profit-balance"><span>可用余额</span><strong>{formatMoney(profitSummary.available)}</strong><small>累计已实现 {formatMoney(profitSummary.net_realized)} · 已分配 {formatMoney(profitSummary.allocated)}</small></div>
        <Link className="secondary-button" to="/profit-ledger">查看收益流水<ArrowRight size={16} /></Link>
      </section>
    </div>
  )
}

function CashControl({ portfolio }: { portfolio: PortfolioSummary }) {
  const capital = portfolio.capital
  const cash = capital?.cash ?? { total: portfolio.balances?.cash ?? 0, cash_equivalent: 0, liquid: portfolio.balances?.cash ?? 0, occupied: 0, available: portfolio.balances?.cash ?? 0, margin_shortfall: 0 }
  const rows = [
    { label: '现金桶本金', value: cash.total, icon: WalletCards },
    { label: 'BOXX 现金等价物', value: cash.cash_equivalent ?? 0, icon: Landmark },
    { label: '账面现金', value: cash.liquid ?? cash.total, icon: Banknote },
    { label: '期权池占用', value: capital?.options?.cash_occupancy ?? 0, icon: CircleDollarSign },
    { label: '可用现金', value: cash.available, icon: Banknote },
    { label: 'Margin 缺口', value: cash.margin_shortfall, icon: ShieldAlert, danger: cash.margin_shortfall > 0 },
  ]
  return <section className={`cash-control-strip ${cash.margin_shortfall > 0 ? 'danger' : ''}`} aria-label="现金占用控制">
    {rows.map(({ label, value, icon: Icon, danger }) => <div className={danger ? 'danger' : ''} key={label}><Icon size={17} /><span>{label}</span><strong>{formatMoney(value)}</strong></div>)}
  </section>
}

function CashTransfer({ onAction, cash, totalCash }: { onAction: (path: string, payload: unknown, method?: 'POST' | 'PATCH' | 'DELETE') => Promise<void>; cash: number; totalCash: number }) {
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    await onAction('/portfolio/transfers', { source: 'cash', target: data.get('target'), amount: Number(data.get('amount')), date: data.get('date'), note: data.get('note') }, 'POST')
    form.reset()
  }
  return <section className="cash-transfer-band"><div><p className="eyebrow">CASH ALLOCATION</p><h2>现金资金分配</h2><p>现金桶余额 {formatMoney(totalCash)} · 当前可转出 {formatMoney(cash)}（含 BOXX 现金等价物）</p></div><form aria-label="现金资金分配" onSubmit={submit}><label>日期<input name="date" type="date" defaultValue={new Date().toISOString().slice(0, 10)} required /></label><label>转入资金桶<select name="target" defaultValue="core"><option value="core">BRK.B 核心仓</option><option value="wheel">期权策略共享池</option></select></label><label>金额<input aria-label="金额" name="amount" type="number" min="0.01" max={cash} step="0.01" required /></label><label>备注<input name="note" /></label><button className="primary-button">确认资金分配</button></form></section>
}

function Metric({ icon: Icon, label, value, tone = '' }: { icon: typeof WalletCards; label: string; value: string; tone?: string }) {
  return <div className="metric"><Icon size={18} /><span>{label}</span><strong className={tone}>{value}</strong></div>
}

function Onboarding({ onInitialize }: { onInitialize: (payload: unknown) => Promise<void> }) {
  const today = new Date().toISOString().slice(0, 10)
  const [age, setAge] = useState('30')
  const [equity, setEquity] = useState('')
  const preview = useMemo(() => allocationPreview(Number(age), Number(equity)), [age, equity])
  return <div className="onboarding"><div className="onboarding-copy"><p className="eyebrow">LOCAL LEDGER SETUP</p><h1>建立账户基线</h1><p>初始总金额按年龄公式进入核心仓、现金与期权共享池，后续新增资金统一进入现金储备。</p></div><form onSubmit={async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    await onInitialize({
      age: Number(data.get('age')),
      opening_equity: Number(data.get('equity')),
      opening_date: data.get('date'),
    })
  }}>
    <label>年龄<input name="age" type="number" value={age} onChange={(event) => setAge(event.target.value)} min="0" max="100" required /></label>
    <label>初始总金额<input name="equity" type="number" value={equity} onChange={(event) => setEquity(event.target.value)} min="0.01" step="0.01" required /></label>
    <label>起始日期<input name="date" type="date" defaultValue={today} required /></label>
    <div className="allocation-preview" aria-label="初始资金公式预览">{preview.map((row) => <div key={row.label}><span>{row.label} · {formatPercent(row.fraction)}</span><strong>{formatMoney(row.amount)}</strong></div>)}</div>
    <button className="primary-button">确认并建立账本</button>
  </form></div>
}

function allocationPreview(age: number, equity: number) {
  const core = Math.min(Math.max(age + 20, 0), 80) / 100
  const cash = .05
  const remaining = Math.max(1 - core - cash, 0)
  const leaps = Math.min(.25, remaining)
  const wheel = remaining - leaps
  return [
    { label: 'BRK.B 核心仓', fraction: core, amount: equity * core },
    { label: '现金储备', fraction: cash, amount: equity * cash },
    { label: '期权策略共享池', fraction: wheel + leaps, amount: equity * (wheel + leaps) },
  ]
}

function formatPercent(value: number) { return `${Number((value * 100).toFixed(1))}%` }
