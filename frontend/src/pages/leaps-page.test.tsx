import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import type { MarketSnapshot, PortfolioSummary, Position } from '../lib/types'
import { LeapsPage } from './LeapsPage'

const portfolio: PortfolioSummary = {
  initialized: true,
  age: 36,
  total_equity: 100000,
  balances: { core: 56000, cash: 5000, wheel: 14000, leaps: 25000, unallocated: 0 },
  targets: {
    core: { fraction: .56, amount: 56000, actual: 56000, variance: 0 },
    cash: { fraction: .05, amount: 5000, actual: 5000, variance: 0 },
    wheel: { fraction: .14, amount: 14000, actual: 14000, variance: 0 },
    leaps: { fraction: .25, amount: 25000, actual: 0, variance: -25000 },
    options: { fraction: .39, amount: 39000, actual: 39000, variance: 0 },
  },
  capital: {
    core: { assigned: 56000, committed: 0, available: 56000, cash_occupancy: 0 },
    cash: { total: 5000, occupied: 0, available: 5000, margin_shortfall: 0 },
    wheel: { assigned: 14000, committed: 0, available: 14000, cash_occupancy: 0 },
    leaps: { assigned: 25000, committed: 0, available: 25000, cash_occupancy: 0 },
    options: { assigned: 39000, committed: 0, available: 39000, cash_occupancy: 0 },
  },
}

const checks = { above_ma200: true, rsi_below_45: true, daily_drop: true, live_quote: true, daily_limit: true }

const market: MarketSnapshot = {
  source: 'yahoo', as_of: '2026-07-22', stale: false,
  market: {
    qqq: { price: 500, ma20: 510, ma200: 450, rsi14: 42, bearish: true, drawdown: .1 },
    tqqq: { price: 80 }, brk_b: { price: 500 }, vix: { price: 20 },
  },
  wheel: { eligible: false, checks: {}, dte_range: [30, 45], delta_range: [.2, .3], reference_strike: 70, preferred_support: null, supports: [] },
  risk: { severity: 'info', stop_required: false, defensive_cc_required_if_holding: false, message: '' },
  leaps: [1, 2, 3, 4, 5].map((tranche) => ({
    tranche,
    eligible: tranche === 1,
    allocation_fraction: .2,
    suggested_amount: tranche === 1 ? 5000 : 0,
    checks: { ...checks, next_slot: tranche === 1 },
  })),
  leaps_fifo: { required: false, candidate: null },
  leaps_technical_ready: true,
  leaps_shared_budget: { target: 39000, current: 0, available: 39000, over: 0 },
  leaps_session: {
    available: true,
    price: 494,
    previous_close: 500,
    change_fraction: -.012,
    quoted_at: '2026-07-22T14:15:00Z',
    market_date: '2026-07-22',
    session: 'pre',
    source: 'yahoo',
  },
}

function position(overrides: Partial<Position> = {}): Position {
  return {
    id: 7, bucket: 'leaps', symbol: 'QQQ', asset_type: 'option', quantity: 1, multiplier: 100,
    entry_price: 100, current_price: 120, current_value: 12000, unrealized_profit: 2000,
    opened_on: '2026-04-13', expiration: '2027-04-13', strike: 400, delta: null, tranche: 1,
    status: 'open', total_loss_impact: 10000, realized_profit: 0,
    quote_source: 'yahoo', quote_bid: 120, quote_ask: 121, quote_last: 120.5, quote_iv: .25,
    quote_as_of: '2026-07-22T20:00:00', peak_bid: 120,
    exit_decision: { code: 'hold', actionable: false, days_held: 100, dte: 265, return_fraction: .2, target_return: .5 },
    ...overrides,
  }
}

describe('LEAPS five-slot console', () => {
  it('switches between QQQ slots and the trillion-club console without stacking both strategies', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><LeapsPage market={market} positions={[]} portfolio={portfolio} /></MemoryRouter>)

    const qqqTab = screen.getByRole('button', { name: /QQQ \/ QLD 五槽位/ })
    const clubTab = screen.getByRole('button', { name: /万亿俱乐部 Long Call/ })
    expect(qqqTab).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('region', { name: 'LEAPS 入场信号' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '万亿俱乐部 LEAPS' })).not.toBeInTheDocument()

    await user.click(clubTab)

    expect(clubTab).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByRole('region', { name: 'LEAPS 入场信号' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: '万亿俱乐部 LEAPS' })).toBeInTheDocument()
  })

  it('shows the live entry signal and five fixed 5% slots', () => {
    render(<MemoryRouter><LeapsPage market={market} positions={[]} portfolio={portfolio} /></MemoryRouter>)

    const signal = screen.getByRole('region', { name: 'LEAPS 入场信号' })
    expect(within(signal).getByText('完成收盘 $500.00')).toBeInTheDocument()
    expect(within(signal).getByText('SMA200 $450.00')).toBeInTheDocument()
    expect(within(signal).getByText('RSI14 42.0')).toBeInTheDocument()
    expect(within(signal).getByText('当前 $494.00')).toBeInTheDocument()
    expect(within(signal).getByText('-1.20%')).toBeInTheDocument()
    expect(within(signal).getByText('同一交易日尚未执行')).toBeInTheDocument()

    for (let slot = 1; slot <= 5; slot += 1) {
      const row = screen.getByRole('article', { name: `LEAPS 容量槽位 ${slot}` })
      expect(row).toHaveTextContent('$5,000.00')
    }
    expect(screen.getByText('尚无 QQQ Call 或 QLD 持仓')).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'LEAPS 容量槽位 1' })).toHaveClass('eligible')
    expect(screen.getByRole('article', { name: 'LEAPS 容量槽位 2' })).not.toHaveClass('eligible')
  })

  it('shows signal slots without exposing manual trade forms', () => {
    render(<MemoryRouter><LeapsPage market={market} positions={[]} portfolio={portfolio} /></MemoryRouter>)

    expect(screen.queryByText('数据来源')).not.toBeInTheDocument()
    expect(screen.queryByText('IBKR 报表同步')).not.toBeInTheDocument()
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /记录槽位|卖出槽位/ })).not.toBeInTheDocument()
  })

  it('marks the FIFO candidate and points to report synchronization', () => {
    const positions = [1, 2, 3, 4, 5].map((tranche) => position({ id: tranche + 6, tranche, opened_on: `2026-0${tranche}-10` }))
    const fifoMarket: MarketSnapshot = {
      ...market,
      leaps: market.leaps.map((decision) => ({ ...decision, eligible: false, checks: { ...decision.checks, next_slot: false } })),
      leaps_fifo: { required: true, candidate: { position_id: 7, slot: 1, opened_on: '2026-01-10' } },
    }
    render(<MemoryRouter><LeapsPage market={fifoMarket} positions={positions} portfolio={portfolio} /></MemoryRouter>)

    const fifoAlert = screen.getByText(/FIFO 换仓候选：槽位 1/).closest('[role="alert"]')
    expect(fifoAlert).toBeInTheDocument()
    const holding = screen.getByRole('article', { name: 'LEAPS 持仓 7' })
    expect(holding).toHaveClass('fifo-candidate')
    expect(within(holding).getByText('FIFO 待轮动')).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'LEAPS 容量槽位 1' })).toHaveClass('fifo')
    expect(fifoAlert).toHaveTextContent('下一份 IBKR 报表会同步槽位记录')
  })

  it('shows QQQ and QLD exit ladders and the QQQ time-forced exit', () => {
    const positions = [
      position({ id: 11, tranche: 1, rolled_from_position_id: 5, exit_decision: { code: 'hold', actionable: false, days_held: 100, dte: 265, return_fraction: .2, target_return: .5 } }),
      position({ id: 12, tranche: 2, exit_decision: { code: 'force_exit', actionable: true, days_held: 271, dte: 94, return_fraction: -.1, target_return: null } }),
      position({ id: 13, tranche: 3, symbol: 'QLD', asset_type: 'equity', multiplier: 1, expiration: null, strike: null, entry_price: 80, current_price: 88, current_value: 88, unrealized_profit: 8, quote_bid: null, quote_ask: null, quote_last: null, quote_iv: null, exit_decision: { code: 'hold', actionable: false, days_held: 100, dte: null, return_fraction: .1, target_return: .25 } }),
      position({ id: 14, tranche: 4, symbol: 'QLD', asset_type: 'equity', multiplier: 1, expiration: null, strike: null, entry_price: 80, current_price: 88, current_value: 88, unrealized_profit: 8, quote_bid: null, quote_ask: null, quote_last: null, quote_iv: null, exit_decision: { code: 'hold', actionable: false, days_held: 150, dte: null, return_fraction: .1, target_return: .15 } }),
      position({ id: 15, tranche: 5, symbol: 'QLD', asset_type: 'equity', multiplier: 1, expiration: null, strike: null, entry_price: 80, current_price: 82, current_value: 82, unrealized_profit: 2, quote_bid: null, quote_ask: null, quote_last: null, quote_iv: null, exit_decision: { code: 'hold', actionable: false, days_held: 220, dte: null, return_fraction: .025, target_return: .05 } }),
    ]
    render(<MemoryRouter><LeapsPage market={market} positions={positions} portfolio={portfolio} /></MemoryRouter>)

    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 11' })).getByText('继续持有 · 目标 50%')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 11' })).getByText('由持仓 #5 展期至当前合约')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 12' })).getByText('持仓超过 270 天，强制平仓')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 13' })).getByText('继续持有 · 目标 25%')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 14' })).getByText('继续持有 · 目标 15%')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 15' })).getByText('继续持有 · 目标 5%')).toBeInTheDocument()
  })

  it('shows an independent trillion-club stock row without manual entry controls', async () => {
    const user = userEvent.setup()
    const clubMarket: MarketSnapshot = {
      ...market,
      leaps_club: {
        decisions: [{
          symbol: 'AAPL', name: 'Apple', technical_eligible: true, eligible: true,
          suggested_slot: 1, suggested_amount: 5000, over_shared_budget: false,
          checks: { qqq_above_ma200: true, stock_above_ma200: true, rsi_below_45: true, daily_drop: true, live_quote: true, market_cap: true, history: true, weekly_limit: true, second_entry: true },
          current_price: 294, previous_close: 312, change_fraction: -.0577, close: 300,
          ma200: 270, rsi14: 41, market_cap: 4_200_000_000_000,
          market_cap_as_of: '2026-06-30', market_cap_currency: 'USD', open_slots: [],
          fifo_candidate_position_id: null, fifo_candidate_slot: null,
          risk_position_ids: [],
        }],
        unavailable: [],
        exclusions: ['000660.KS', 'MU', 'SPACEX'],
      },
    }
    const clubPosition = position({ id: 21, symbol: 'AAPL', leaps_category: 'club', tranche: 1 })
    render(<MemoryRouter><LeapsPage market={clubMarket} positions={[clubPosition]} portfolio={portfolio} /></MemoryRouter>)

    await user.click(screen.getByRole('button', { name: /万亿俱乐部 Long Call/ }))
    expect(screen.getByRole('region', { name: '万亿俱乐部当前持仓' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'LEAPS 持仓 21' })).toBeInTheDocument()
    const row = screen.getByRole('article', { name: 'AAPL 万亿俱乐部' })
    expect(within(row).getByText('$4.20T · 2026-06-30')).toBeInTheDocument()
    expect(within(row).getByText('RSI 41.0')).toHaveClass('pass')
    expect(screen.getByText(/明确排除 MU、ORCL、WMT/)).toBeInTheDocument()
    expect(screen.queryByText('数据来源')).not.toBeInTheDocument()
    expect(within(row).queryByText('IBKR 报表同步')).not.toBeInTheDocument()
    expect(within(row).queryByRole('form')).not.toBeInTheDocument()
  })

  it('shows the realized loss from the closed contract inside a rolled synthetic holding', async () => {
    const user = userEvent.setup()
    const previous = position({
      id: 5,
      symbol: 'MSFT',
      leaps_category: 'club',
      quantity: 0,
      entry_price: 50,
      current_price: 45,
      current_value: 0,
      unrealized_profit: null,
      opened_on: '2026-05-04',
      expiration: '2026-12-18',
      strike: 400,
      status: 'closed',
      closed_on: '2026-08-28',
      realized_profit: -1000,
    })
    const current = position({
      id: 6,
      symbol: 'MSFT',
      leaps_category: 'club',
      quantity: 2,
      entry_price: 47.5,
      current_price: 49,
      current_value: 9800,
      unrealized_profit: 300,
      opened_on: '2026-08-28',
      expiration: '2027-06-18',
      strike: 390,
      rolled_from_position_id: 5,
    })

    render(<MemoryRouter><LeapsPage market={market} positions={[current, previous]} portfolio={portfolio} /></MemoryRouter>)
    await user.click(screen.getByRole('button', { name: /万亿俱乐部 Long Call/ }))

    const roll = screen.getByRole('region', { name: 'MSFT 展期记录 5 到 6' })
    expect(within(roll).getByText('2026-12-18 $400 Call')).toBeInTheDocument()
    expect(within(roll).getByText('平仓 $45.00')).toBeInTheDocument()
    expect(within(roll).getByText('已实现 -$1,000.00')).toHaveClass('negative')
    expect(within(roll).getByText('净支出 $500.00')).toBeInTheDocument()
  })

  it('orders trillion-club stocks from the largest daily drop to the largest gain', async () => {
    const user = userEvent.setup()
    const baseDecision = {
      name: 'Apple', technical_eligible: false, eligible: false,
      suggested_slot: 1, suggested_amount: 0, over_shared_budget: false,
      checks: { qqq_above_ma200: true, stock_above_ma200: true, rsi_below_45: false, daily_drop: false, live_quote: true, market_cap: true, history: true, weekly_limit: true, second_entry: true },
      current_price: 300, previous_close: 300, close: 300, ma200: 270, rsi14: 50,
      market_cap: 2_000_000_000_000, market_cap_as_of: '2026-06-30', market_cap_currency: 'USD',
      open_slots: [], fifo_candidate_position_id: null, fifo_candidate_slot: null, risk_position_ids: [],
    }
    const sortedMarket: MarketSnapshot = {
      ...market,
      leaps_club: {
        decisions: [
          { ...baseDecision, symbol: 'NVDA', name: 'NVIDIA', change_fraction: .021 },
          { ...baseDecision, symbol: 'AAPL', name: 'Apple', change_fraction: -.061 },
          { ...baseDecision, symbol: 'MSFT', name: 'Microsoft', change_fraction: -.018 },
        ],
        unavailable: [],
        exclusions: [],
      },
    }

    render(<MemoryRouter><LeapsPage market={sortedMarket} positions={[]} portfolio={portfolio} /></MemoryRouter>)

    await user.click(screen.getByRole('button', { name: /万亿俱乐部 Long Call/ }))
    expect(screen.getAllByRole('article', { name: /万亿俱乐部/ }).map((row) => row.getAttribute('aria-label'))).toEqual([
      'AAPL 万亿俱乐部',
      'MSFT 万亿俱乐部',
      'NVDA 万亿俱乐部',
    ])
  })
})
