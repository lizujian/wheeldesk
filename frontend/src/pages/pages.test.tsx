import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { SignalBanner } from '../components/SignalBanner'
import { LeapsPage } from './LeapsPage'
import { LedgerPage } from './LedgerPage'
import { OverviewPage } from './OverviewPage'
import { SettingsPage } from './SettingsPage'
import { WheelPage } from './WheelPage'
import type { MarketSnapshot, PortfolioSummary, WheelOverview } from '../lib/types'

const portfolio: PortfolioSummary = {
  initialized: true,
  age: 30,
  currency: 'USD',
  total_equity: 100000,
  net_external_capital: 95000,
  investment_profit: 5000,
  balances: { core: 45000, cash: 5000, wheel: 25000, leaps: 25000, unallocated: 0 },
  targets: {
    core: { fraction: 0.5, amount: 50000, actual: 45000, variance: -5000 },
    cash: { fraction: 0.05, amount: 5000, actual: 5000, variance: 0 },
    wheel: { fraction: 0.2, amount: 20000, actual: 25000, variance: 5000 },
    leaps: { fraction: 0.25, amount: 25000, actual: 25000, variance: 0 },
    options: { fraction: 0.45, amount: 45000, actual: 50000, variance: 5000 },
  },
}

const market: MarketSnapshot = {
  source: 'sample',
  as_of: '2026-07-09',
  stale: false,
  market: {
    qqq: { price: 510, ma20: 508, ma200: 480, rsi14: 44, bearish: true, drawdown: 0.1 },
    tqqq: { price: 100 },
    brk_b: { price: 490 },
    vix: { price: 22 },
  },
  wheel: {
    eligible: true,
    checks: { above_ma200: true, rsi_below_50: true, bearish_candle: true },
    dte_range: [30, 45],
    delta_range: [0.2, 0.3],
    reference_strike: 87,
    preferred_support: { price: 87, kind: 'swing_cluster', touches: 3, distance_pct: 0.13 },
    supports: [{ price: 87, kind: 'swing_cluster', touches: 3, distance_pct: 0.13 }],
  },
  risk: {
    severity: 'info',
    stop_required: false,
    defensive_cc_required_if_holding: false,
    message: '未触发 QQQ MA200 高危规则。',
  },
  leaps: [1, 2, 3, 4, 5].map((tranche) => ({ tranche, eligible: false, allocation_fraction: 0.2, suggested_amount: 0, checks: { live_quote: false, next_slot: tranche === 1 } })),
  leaps_fifo: { required: false, candidate: null },
  leaps_session: { available: false, price: 505, previous_close: 510, change_fraction: -0.0098, quoted_at: null, market_date: '2026-07-09', session: 'sample', source: 'sample' },
}

const wheel: WheelOverview = {
  budget: {
    budget: 20000,
    target_fraction: 0.2,
    funded: 0,
    funding_gap: 20000,
    funding_excess: 0,
    unfunded_exposure: 0,
    exposure: 0,
    available: 20000,
    over_budget: 0,
    usage_fraction: 0,
  },
  recommendations: { first: 12000, second: 8000 },
  realized_profit: 0,
  rounds: [],
}

describe('operating pages', () => {
  it('previews formula allocations and initializes without manual bucket amounts', async () => {
    const user = userEvent.setup()
    const onInitialize = vi.fn().mockResolvedValue(undefined)
    render(<MemoryRouter><OverviewPage portfolio={{ initialized: false }} profitSummary={{ wheel_realized: 0, leaps_realized: 0, other_realized: 0, net_realized: 0, allocated: 0, available: 0 }} onInitialize={onInitialize} /></MemoryRouter>)

    await user.type(screen.getByLabelText('初始总金额'), '100000')
    expect(screen.getByText('BRK.B 核心仓 · 50%')).toBeInTheDocument()
    expect(screen.getByText('现金储备 · 5%')).toBeInTheDocument()
    expect(screen.getByText('期权策略共享池 · 45%')).toBeInTheDocument()
    expect(screen.getByText('$45,000.00')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认并建立账本' }))

    expect(onInitialize).toHaveBeenCalledWith({
      age: 30,
      opening_equity: 100000,
      opening_date: expect.any(String),
    })
    expect(screen.queryByRole('spinbutton', { name: 'BRK.B' })).not.toBeInTheDocument()
  })

  it('shows actual allocation and target variance', () => {
    render(<MemoryRouter><OverviewPage portfolio={portfolio} profitSummary={{ wheel_realized: 2400, leaps_realized: 5600, other_realized: 0, net_realized: 8000, allocated: 3000, available: 5000 }} onInitialize={async () => {}} onAction={async () => {}} /></MemoryRouter>)

    expect(screen.getByText('$100,000.00')).toBeInTheDocument()
    expect(screen.getAllByText('BRK.B 核心仓')).toHaveLength(2)
    expect(screen.getByText('低配 $5,000.00')).toBeInTheDocument()
    expect(screen.getByText('当前可分配收益')).toBeInTheDocument()
    expect(within(screen.getByText('可用余额').parentElement!).getByText('$5,000.00')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看收益流水' })).toHaveAttribute('href', '/profit-ledger')
  })

  it('calculates target gaps from deployed positions instead of assigned buckets', () => {
    render(<MemoryRouter><OverviewPage portfolio={{
      ...portfolio,
      deployments: { core: 7000, cash: 5000, wheel: 40000, leaps: 0, options: 40000 },
    }} profitSummary={{ wheel_realized: 0, leaps_realized: 0, other_realized: 0, net_realized: 0, allocated: 0, available: 0 }} onInitialize={async () => {}} /></MemoryRouter>)

    expect(screen.getByText('低配 $43,000.00')).toBeInTheDocument()
    expect(screen.getByText('低配 $5,000.00')).toBeInTheDocument()
    expect(screen.getByText('实际部署')).toBeInTheDocument()
  })

  it('shows wheel budget, support rationale, and contract window', () => {
    render(<MemoryRouter><WheelPage market={market} overview={wheel} /></MemoryRouter>)

    expect(screen.getByText('期权共享本金')).toBeInTheDocument()
    expect(screen.getByText('$12,000.00')).toBeInTheDocument()
    expect(screen.getByText('$8,000.00')).toBeInTheDocument()
    expect(screen.getAllByText('$87.00')).toHaveLength(2)
    expect(screen.getByText(/触及 3 次/)).toBeInTheDocument()
    expect(screen.getByText(/30–45 DTE/)).toBeInTheDocument()
  })

  it('renders all five LEAPS slots and sample-data provenance', () => {
    render(
      <MemoryRouter>
        <LeapsPage market={market} positions={[]} portfolio={{
          ...portfolio,
          balances: { ...portfolio.balances!, leaps: 0 },
          targets: { ...portfolio.targets!, leaps: { fraction: 0.25, amount: 25000, actual: 0, variance: -25000 } },
        }} />
      </MemoryRouter>,
    )

    for (let slot = 1; slot <= 5; slot += 1) expect(screen.getByRole('article', { name: `LEAPS 容量槽位 ${slot}` })).toBeInTheDocument()
    expect(screen.getByText('模拟数据')).toBeInTheDocument()
    expect(screen.getByText('期权共享本金')).toBeInTheDocument()
    expect(screen.getByText('共享成本占用')).toBeInTheDocument()
    expect(screen.getByText('共享可用本金')).toBeInTheDocument()
    expect(screen.getByText(/车轮与 LEAPS 共同目标 45.0%/)).toBeInTheDocument()
  })

  it('shows a read-only operation ledger sourced from IBKR reports', () => {
    render(<LedgerPage events={[]} />)

    expect(screen.getByRole('heading', { name: '操作流水' })).toBeInTheDocument()
    expect(screen.getByText('证券交易与入金来自 IBKR 报表')).toBeInTheDocument()
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '记录新增资金' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '资金分配' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '录入持仓' })).not.toBeInTheDocument()
  })

  it('moves ordinary cash allocation controls to the overview', async () => {
    const user = userEvent.setup()
    const onAction = vi.fn().mockResolvedValue(undefined)
    render(<MemoryRouter><OverviewPage portfolio={portfolio} profitSummary={{ wheel_realized: 0, leaps_realized: 0, other_realized: 0, net_realized: 0, allocated: 0, available: 0 }} onInitialize={async () => {}} onAction={onAction} /></MemoryRouter>)

    const form = screen.getByRole('form', { name: '现金资金分配' })
    await user.selectOptions(within(form).getByLabelText('转入资金桶'), 'core')
    await user.type(within(form).getByLabelText('金额'), '3000')
    await user.click(within(form).getByRole('button', { name: '确认资金分配' }))

    expect(onAction).toHaveBeenCalledWith('/portfolio/transfers', expect.objectContaining({ source: 'cash', target: 'core', amount: 3000 }), 'POST')
  })

  it('shows occupied cash and caps transfers at available cash', () => {
    const withCapital = {
      ...portfolio,
      capital: {
        core: { assigned: 45000, committed: 10000, available: 35000, cash_occupancy: 0 },
        wheel: { assigned: 37000, committed: 40000, available: 0, cash_occupancy: 3000 },
        leaps: { assigned: 8000, committed: 10000, available: 0, cash_occupancy: 2000 },
        options: { assigned: 45000, committed: 50000, available: 0, cash_occupancy: 5000 },
        cash: { total: 10000, occupied: 5000, available: 5000, margin_shortfall: 0 },
      },
    }
    render(<MemoryRouter><OverviewPage portfolio={withCapital} profitSummary={{ wheel_realized: 0, leaps_realized: 0, other_realized: 0, net_realized: 0, allocated: 0, available: 0 }} onInitialize={async () => {}} /></MemoryRouter>)

    expect(screen.getByText('期权池占用')).toBeInTheDocument()
    expect(screen.getByText('可用现金')).toBeInTheDocument()
    expect(screen.getByText('Margin 缺口')).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: '金额' })).toHaveAttribute('max', '5000')
    expect(screen.queryByText('待分配')).not.toBeInTheDocument()
  })

  it('renders critical MA200 risk as an alert', () => {
    render(
      <SignalBanner
        risk={{
          severity: 'critical',
          stop_required: true,
          defensive_cc_required_if_holding: true,
          message: '跌破牛熊分界线，立即评估平仓止损！',
        }}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('跌破牛熊分界线')
    expect(screen.getByRole('alert')).toHaveTextContent('近价或价内 Covered Call')
  })

  it('requires a second typed confirmation before resetting all data', async () => {
    const user = userEvent.setup()
    const onReset = vi.fn().mockResolvedValue(undefined)
    render(
      <MemoryRouter>
        <SettingsPage portfolio={portfolio} market={market} onReset={onReset} />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: '重置全部数据' }))
    const dialog = screen.getByRole('dialog', { name: '确认重置全部数据' })
    const finalButton = screen.getByRole('button', { name: '永久清空数据' })
    expect(dialog).toBeInTheDocument()
    expect(finalButton).toBeDisabled()

    await user.type(screen.getByLabelText('输入 RESET 继续'), 'RESET')
    expect(finalButton).toBeEnabled()
    await user.click(finalButton)

    expect(onReset).toHaveBeenCalledTimes(1)
  })
})
