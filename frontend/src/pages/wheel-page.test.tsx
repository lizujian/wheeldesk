import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import type { MarketSnapshot, WheelOverview } from '../lib/types'
import { WheelHistoryPage, WheelPage } from './WheelPage'

const market: MarketSnapshot = {
  source: 'yahoo',
  as_of: '2026-07-18',
  stale: false,
  market: {
    qqq: { price: 510, ma20: 508, ma200: 480, rsi14: 44, bearish: true, drawdown: 0.1 },
    tqqq: { price: 55 },
    brk_b: { price: 490 },
    vix: { price: 22 },
  },
  wheel: {
    eligible: true,
    checks: { above_ma200: true, rsi_below_50: true, bearish_candle: true },
    dte_range: [30, 45],
    delta_range: [0.2, 0.3],
    reference_strike: 50,
    preferred_support: { price: 50, kind: 'swing_cluster', touches: 3, distance_pct: 0.09 },
    supports: [{ price: 50, kind: 'swing_cluster', touches: 3, distance_pct: 0.09 }],
  },
  risk: {
    severity: 'info',
    stop_required: false,
    defensive_cc_required_if_holding: false,
    message: '未触发 QQQ MA200 高危规则。',
  },
  leaps: [],
}

const overview: WheelOverview = {
  capital: {
    assigned: 100000,
    put_collateral: 96000,
    share_capital: 20000,
    committed: 116000,
    available: 0,
    cash_occupancy: 16000,
    cash_available: 0,
    margin_shortfall: 6000,
  },
  budget: {
    budget: 100000,
    target_fraction: 0.39,
    funded: 100000,
    funding_gap: 0,
    funding_excess: 0,
    unfunded_exposure: 0,
    exposure: 116000,
    available: 0,
    over_budget: 16000,
    usage_fraction: 1.16,
  },
  recommendations: { first: 0, second: 0 },
  realized_profit: 1800,
  rounds: [{
    id: 1,
    number: 1,
    opened_on: '2026-06-01',
    closed_on: null,
    status: 'active',
    realized_profit: 1800,
    voided_at: null,
    void_reason: null,
    puts: [{
      id: 11,
      round_id: 1,
      symbol: 'TQQQ',
      batch_number: 1,
      trade_date: '2026-06-01',
      expiration: '2026-07-17',
      strike: 50,
      premium: 1.5,
      quantity: 12,
      open_quantity: 0,
      assigned_contracts: 12,
      entry_tqqq_price: 55,
      earnings_confirmed: false,
      state: 'assigned',
      closed_on: '2026-07-17',
      close_premium: null,
      realized_profit: 1800,
      collateral: 0,
      opening_dte: 46,
      opening_annualized_return: 0.238043,
      early_close_days: null,
      early_close_annualized_return: null,
      early_close_return_kind: null,
      quote_source: null,
      quote_bid: null,
      quote_ask: null,
      quote_last: null,
      quote_iv: null,
      quote_as_of: null,
      theoretical_low: null,
      theoretical_base: null,
      theoretical_high: null,
      captured_fraction: null,
      early_close_code: null,
      early_close_message: null,
      voided_at: null,
      void_reason: null,
      share_lots: [{
        id: 21,
        put_lot_id: 11,
        assigned_on: '2026-07-17',
        assignment_strike: 50,
        original_quantity: 1200,
        remaining_quantity: 1200,
        state: 'held',
        realized_profit: 0,
        capital: 60000,
        covered_contracts: 6,
        available_call_contracts: 6,
        voided_at: null,
        void_reason: null,
        calls: [{
          id: 31,
          share_lot_id: 21,
          trade_date: '2026-07-18',
          expiration: '2026-08-21',
          strike: 52,
          premium: 1.2,
          quantity: 6,
          state: 'open',
          closed_on: null,
          close_premium: null,
          realized_profit: 0,
          quote_source: 'public',
          quote_bid: 0.72,
          quote_ask: 0.78,
          quote_last: 0.75,
          quote_iv: 0.61,
          quote_as_of: '2026-07-18T20:00:00',
          voided_at: null,
          void_reason: null,
        }],
      }],
    }, {
      id: 12,
      round_id: 1,
      symbol: 'TQQQ',
      batch_number: 2,
      trade_date: '2026-07-01',
      expiration: '2026-08-21',
      strike: 45,
      premium: 1.8,
      quantity: 8,
      open_quantity: 8,
      assigned_contracts: 0,
      entry_tqqq_price: 49,
      earnings_confirmed: false,
      state: 'open',
      closed_on: null,
      close_premium: null,
      realized_profit: 0,
      collateral: 36000,
      opening_dte: 51,
      opening_annualized_return: 0.286275,
      early_close_days: 20,
      early_close_annualized_return: 0.1752,
      early_close_return_kind: 'estimated',
      quote_source: 'theoretical',
      quote_bid: null,
      quote_ask: null,
      quote_last: null,
      quote_iv: null,
      quote_as_of: null,
      theoretical_low: 0.55,
      theoretical_base: 0.65,
      theoretical_high: 0.72,
      captured_fraction: 0.6,
      early_close_code: 'expiry_profit',
      early_close_message: '进入止盈区，请在券商确认实际买回价格。',
      voided_at: null,
      void_reason: null,
      share_lots: [],
    }],
  }],
}

function renderWheel(props: { market?: MarketSnapshot; overview?: WheelOverview } = {}) {
  return render(<MemoryRouter><WheelPage market={props.market ?? market} overview={props.overview ?? overview} /></MemoryRouter>)
}

describe('two-batch wheel console', () => {
  it('shows budget, simultaneous lot states, quote provenance, and profit signal', () => {
    renderWheel()

    expect(screen.getByText('期权共享本金')).toBeInTheDocument()
    expect(screen.getByText('期权共享目标')).toBeInTheDocument()
    expect(screen.getByText('超过共享目标')).toBeInTheDocument()
    expect(screen.getAllByText('$16,000.00').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Put 担保')).toBeInTheDocument()
    expect(screen.getByText('接股本金')).toBeInTheDocument()
    expect(screen.getByText('共享总占用')).toBeInTheDocument()
    expect(screen.getByText('临时占用现金')).toBeInTheDocument()
    expect(screen.getByText('Margin 缺口')).toBeInTheDocument()
    expect(screen.getByText('$116,000.00')).toBeInTheDocument()
    expect(screen.getByRole('alert', { name: '车轮资金风险' })).toHaveTextContent('Margin 缺口 $6,000.00')
    expect(screen.getByText('策略缩减期')).toBeInTheDocument()
    expect(screen.getByText(/期权合计占用已超过共享目标/)).toBeInTheDocument()
    expect(screen.getByText('第 1 轮 · 第一批')).toBeInTheDocument()
    expect(screen.getByText('第 1 轮 · 第二批')).toBeInTheDocument()
    expect(screen.getByText('Covered Call #31')).toBeInTheDocument()
    expect(screen.getByText('公开报价')).toBeInTheDocument()
    expect(screen.getByText('理论估算')).toBeInTheDocument()
    expect(screen.getByText(/已捕获 60.0% 权利金/)).toBeInTheDocument()
    expect(screen.getAllByText('开仓年化收益')).toHaveLength(2)
    expect(screen.getByText('28.63%')).toBeInTheDocument()
    expect(screen.getAllByText('当前提前平仓估算年化')).toHaveLength(2)
    expect(screen.getAllByText('17.52%').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/券商确认实际买回价格/).closest('[role="alert"]')).toBeInTheDocument()
    expect(screen.queryByLabelText('车轮阶段')).not.toBeInTheDocument()
  })

  it('labels a same-day closed Put as actual even when annualization is unavailable', () => {
    const closedPut = {
      ...overview.rounds[0].puts[1],
      state: 'closed' as const,
      open_quantity: 0,
      early_close_days: 0,
      early_close_annualized_return: null,
      early_close_return_kind: null,
    }
    const closedOverview = {
      ...overview,
      rounds: [{ ...overview.rounds[0], puts: [closedPut] }],
    }

    const main = render(<MemoryRouter><WheelPage market={market} overview={closedOverview} /></MemoryRouter>)
    expect(screen.queryByText(`Sell Put #${closedPut.id}`)).not.toBeInTheDocument()
    main.unmount()

    render(<MemoryRouter><WheelHistoryPage overview={closedOverview} /></MemoryRouter>)

    expect(screen.getByText('实际提前平仓年化')).toBeInTheDocument()
    expect(screen.queryByText('当前提前平仓估算年化')).not.toBeInTheDocument()
  })

  it('shows an imported club Put roll on the live position and in history', async () => {
    const user = userEvent.setup()
    const roll = {
      from_put_id: 5,
      to_put_id: 6,
      rolled_on: '2026-08-26',
      from_expiration: '2026-08-28',
      from_strike: 250,
      to_expiration: '2026-09-25',
      to_strike: 250,
      buyback_premium: 10,
      new_premium: 12,
      quantity: 1,
      net_credit: 200,
      previous_realized_profit: -600,
    }
    const source = overview.rounds[0].puts[1]
    const oldPut = {
      ...source,
      id: 5,
      symbol: 'AAPL',
      batch_number: 1 as const,
      trade_date: '2026-08-14',
      expiration: '2026-08-28',
      strike: 250,
      premium: 4,
      quantity: 1,
      open_quantity: 0,
      state: 'rolled' as const,
      closed_on: '2026-08-26',
      close_premium: 10,
      realized_profit: -600,
      collateral: 0,
      roll_count: 0,
      rolled_from: null,
      rolled_to: roll,
    }
    const currentPut = {
      ...source,
      id: 6,
      symbol: 'AAPL',
      batch_number: 1 as const,
      trade_date: '2026-08-26',
      expiration: '2026-09-25',
      strike: 250,
      premium: 12,
      quantity: 1,
      open_quantity: 1,
      state: 'open' as const,
      closed_on: null,
      close_premium: null,
      realized_profit: 0,
      collateral: 25000,
      roll_count: 1,
      rolled_from: roll,
      rolled_to: null,
    }
    const rolledOverview = {
      ...overview,
      rounds: [{ ...overview.rounds[0], realized_profit: -600, puts: [oldPut, currentPut] }],
    }

    const live = renderWheel({ overview: rolledOverview })
    await user.click(screen.getByRole('button', { name: /万亿俱乐部车轮/ }))
    expect(screen.getByText('第 1 次展期')).toBeInTheDocument()
    expect(screen.getByText(/2026-08-28 \$250.00 Put/)).toBeInTheDocument()
    expect(screen.getByText('净收 $200.00')).toBeInTheDocument()
    expect(screen.getAllByText('-$600.00').length).toBeGreaterThanOrEqual(1)
    live.unmount()

    render(<MemoryRouter><WheelHistoryPage overview={rolledOverview} /></MemoryRouter>)
    expect(screen.getByText('已展期')).toBeInTheDocument()
    expect(screen.getByText('已展期至新合约')).toBeInTheDocument()
    expect(screen.getByText('净收 $200.00')).toBeInTheDocument()
  })

  it('shows a trillion-club candidate without manual entry controls', async () => {
    const user = userEvent.setup()
    const clubMarket: MarketSnapshot = {
      ...market,
      wheel_club: {
        weekly_limit_days: 7,
        single_stock_fraction: 0.05,
        unavailable: [],
        decisions: [{
          symbol: 'AAPL', name: 'Apple', technical_eligible: true, eligible: false,
          checks: { qqq_above_ma200: true, stock_above_ma200: true, rsi_below_40: true, daily_drop: true, confirmed_support: true, earnings_clear: true, live_quote: true, market_cap: true, history: true, weekly_limit: true, no_active_cycle: true },
          current_price: 194, previous_close: 205, change_fraction: -0.0537, close: 200, ma200: 180, rsi14: 38,
          preferred_support: { price: 170, kind: 'swing_cluster', touches: 3, distance_pct: 0.12 },
          supports: [{ price: 170, kind: 'swing_cluster', touches: 3, distance_pct: 0.12 }],
          reference_strike: 170, dte_range: [30, 45], delta_range: [0.15, 0.25], minimum_annualized_return: 0.12,
          one_contract_collateral: 17000, concentration_limit: 15000, budget_available: 14000,
          over_concentration: true, over_budget: true, active_cycle: false,
          next_earnings_date: '2026-11-01', earnings_available: true, earnings_confirmation_required: true,
          high_risk_put_ids: [],
        }],
      },
    }
    renderWheel({ market: clubMarket })

    await user.click(screen.getByRole('button', { name: /万亿俱乐部车轮/ }))
    const row = screen.getByRole('article', { name: 'AAPL 万亿俱乐部车轮' })
    expect(within(row).getByText('-5.37%')).toBeInTheDocument()
    expect(within(row).getByText('超过可用预算')).toBeInTheDocument()
    expect(screen.queryByText('数据来源')).not.toBeInTheDocument()
    expect(within(row).queryByText('IBKR 报表同步')).not.toBeInTheDocument()
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
  })

  it('does not expose manual add, edit, settle, or delete controls', () => {
    renderWheel()

    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /编辑|撤销误录|提前平仓|到期归零|确认接股|确认扣走/ })).not.toBeInTheDocument()
  })
})
