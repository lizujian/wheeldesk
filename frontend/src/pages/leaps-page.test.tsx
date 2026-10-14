import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import type { ClubEntryDecision, MarketSnapshot, OtherHolding, PortfolioSummary, Position } from '../lib/types'
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

function clubDecision(overrides: Partial<ClubEntryDecision> = {}): ClubEntryDecision {
  return {
    symbol: 'AAPL', name: 'Apple', technical_eligible: false, eligible: false,
    suggested_slot: null, suggested_amount: 0, over_shared_budget: false,
    checks: { qqq_above_ma200: true, stock_above_ma200: true, rsi_below_45: false, daily_drop: false, live_quote: true, market_cap: true, history: true, weekly_limit: true, second_entry: true },
    current_price: 300, previous_close: 300, change_fraction: 0, close: 300,
    ma200: 270, rsi14: 50, market_cap: 2_000_000_000_000,
    market_cap_as_of: '2026-06-30', market_cap_currency: 'USD', open_slots: [],
    fifo_candidate_position_id: null, fifo_candidate_slot: null, risk_position_ids: [],
    ...overrides,
  }
}

function showHoldingsTab() {
  fireEvent.click(screen.getByRole('tab', { name: /当前持仓/ }))
}

describe('LEAPS combined console', () => {
  it('shows per-symbol cost and signed net cash flow after IV, including zero and absent holdings', () => {
    const value: MarketSnapshot = { ...market, leaps_watchlist: [
      ['QQQ', 5000, 300], ['DRAM', 1068, -36], ['AAPL', 0, 0], ['SOXX', null, null],
    ].map(([symbol, committed, cashFlow]) => ({
      symbol: String(symbol), name: String(symbol), price: 50, change_fraction: 0, ma200: 45, rsi14: 40,
      source: 'ibkr', error: null, iv: null, iv_error: null,
      holding_occupancy: committed == null ? null : { committed: Number(committed), net_cash_flow: Number(cashFlow) },
    })) }
    render(<MemoryRouter><LeapsPage market={value} positions={[]} portfolio={portfolio} /></MemoryRouter>)
    const list = screen.getByRole('region', { name: 'LEAPS 股票列表' })
    expect(within(list).getAllByRole('columnheader').map((header) => header.textContent))
      .toEqual(['股票', '当前价', '日涨跌', 'RSI14', 'IV', '当前持仓占用', '说明'])
    for (const [symbol, expected] of [['QQQ', '$5,000.00（+$300.00）'], ['DRAM', '$1,068.00（-$36.00）'], ['AAPL', '$0.00（$0.00）'], ['SOXX', '-']]) {
      const row = within(list).getByRole('row', { name: new RegExp(`^${symbol}`) })
      expect(within(row).getAllByRole('cell')[5].textContent).toBe(expected)
    }
    expect(within(list).getByText('（+$300.00）')).toHaveClass('positive')
    expect(within(list).getByText('（-$36.00）')).toHaveClass('negative')
  })

  it.each(['etf', 'club'] as const)('manages DRAM Long and Short together even with cached category %s', (category) => {
    const long = position({ id: 9, symbol: 'DRAM', leaps_category: category, entry_price: 10.68, current_price: 10.65, quote_bid: 10.65, strike: 50, expiration: '2027-06-17', current_value: 1065 })
    const call: OtherHolding = {
      id: 30, category: 'leaps_call_wheel', symbol: 'DRAM', asset_type: 'option', direction: 'short', option_type: 'call',
      quantity: 1, multiplier: 100, entry_price: 1.52, current_price: 1.88, current_value: -188, absolute_value: 188,
      unrealized_profit: -36, opened_on: '2026-10-13', expiration: '2026-10-30', strike: 55, status: 'open', closed_on: null,
      exit_price: null, realized_profit: null, quote_source: 'ibkr', quote_as_of: '2026-10-14', quote_status: 'updated', last_error: null, linked_position_id: 9,
    }
    render(<MemoryRouter><LeapsPage market={market} positions={[long]} portfolio={portfolio} leapsCalls={[call]} /></MemoryRouter>)
    showHoldingsTab()
    const register = screen.getByRole('region', { name: 'DRAM / SOXX 当前持仓' })
    expect(within(register).getByRole('article', { name: 'LEAPS 持仓 9' })).toHaveTextContent('$10.68')
    expect(within(register).getByRole('article', { name: 'DRAM PMCC Short Call 30' })).toHaveTextContent('关联 Long Call #9')
    expect(within(register).getByText('-$36.00')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: '万亿俱乐部当前持仓' })).queryByText('DRAM')).not.toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'QQQ / QLD 当前持仓' })).queryByText('DRAM')).not.toBeInTheDocument()
  })

  it('explains unmet indicators using actual decisions even when displayed intraday price crosses MA200', () => {
    const value = { ...market, leaps_club: { decisions: [clubDecision({ checks: { stock_above_ma200: false, rsi_below_45: true, daily_drop: false, live_quote: false } })], unavailable: [], exclusions: [] } }
    render(<MemoryRouter><LeapsPage market={value} positions={[]} portfolio={portfolio} /></MemoryRouter>)
    const row = screen.getByRole('row', { name: /AAPL.*Apple/ })
    expect(row).not.toHaveTextContent('已满足：')
    expect(row).toHaveTextContent('未满足：标的收盘高于 MA200、当日跌幅 > 5%、有效实时行情')
    expect(row).not.toHaveTextContent('当前满足入场条件')
  })

  it('shows VIX snapshot, intraday 52-week high and empirical percentile with sample count', () => {
    const value: MarketSnapshot = { ...market, vix_context: {
      price: 15.19, price_kind: 'snapshot', source: 'ibkr', quality: 'delayed', market_as_of: null, fetched_at: '2026-10-14T10:00:00Z',
      close_as_of: '2026-10-13', high_52w: 35.3, high_52w_as_of: '2026-03-09', percentile_fraction: .125, sample_size: 252,
      window_start: '2025-10-15', window_end: '2026-10-14', error: null, history_error: null,
    } }
    render(<MemoryRouter><LeapsPage market={value} positions={[]} portfolio={portfolio} /></MemoryRouter>)
    const band = screen.getByRole('region', { name: 'VIX 市场环境' })
    for (const text of ['15.19', '35.30', '12.5%']) expect(within(band).getByText(text)).toBeInTheDocument()
    expect(band).toHaveTextContent('刷新时行情 · 延迟')
    expect(band).toHaveTextContent('252 日样本')
    expect(band).toHaveTextContent('2025-10-15 至 2026-10-14')
  })

  it('explains ETF signals with the club thresholds and does not duplicate ETF list rows', () => {
    const value: MarketSnapshot = { ...market, leaps_etfs: { decisions: [clubDecision({ symbol: 'SOXX', checks: {
      stock_above_ma200: true, rsi_below_45: true, daily_drop: false, weekly_limit: false, live_quote: false,
    } })], unavailable: [] } }
    render(<MemoryRouter><LeapsPage market={value} positions={[]} portfolio={portfolio} /></MemoryRouter>)
    const rows = screen.getAllByRole('row', { name: /SOXX/ })
    expect(rows).toHaveLength(1)
    expect(rows[0]).not.toHaveTextContent('已满足：')
    expect(rows[0]).toHaveTextContent('未满足：当日跌幅 > 5%、本周开仓限频、有效实时行情')
    expect(rows[0]).not.toHaveTextContent('买入信号尚未配置')
  })
  it('shows a QLD replacement Sell Call in the QQQ / QLD register', () => {
    const qldCall: OtherHolding = {
      id: 19, category: 'leaps_call_wheel', symbol: 'QLD', asset_type: 'option', direction: 'short', option_type: 'call',
      quantity: 1, multiplier: 100, entry_price: 2.12, current_price: 2.64, current_value: -264, absolute_value: 264,
      unrealized_profit: -52, opened_on: '2026-09-04', expiration: '2026-09-18', strike: 90, status: 'open', closed_on: null,
      exit_price: null, realized_profit: null, quote_source: 'ibkr_statement', quote_as_of: '2026-09-04', quote_status: 'updated', last_error: null,
      linked_position_id: 2,
    }
    render(<MemoryRouter><LeapsPage market={market} positions={[]} portfolio={portfolio} leapsCalls={[qldCall]} /></MemoryRouter>)
    showHoldingsTab()

    const register = screen.getByRole('region', { name: 'QQQ / QLD 当前持仓' })
    const cluster = within(register).getByRole('region', { name: 'QLD 策略簇' })
    expect(within(cluster).getByText('PMCC Short Call')).toBeInTheDocument()
    expect(within(cluster).getByRole('heading', { name: 'QLD' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '万亿俱乐部 LEAPS' })).toBeInTheDocument()
  })

  it('shows a covered LEAPS Sell Call under the matching club register', () => {
    const leapsCall: OtherHolding = {
      id: 18, category: 'leaps_call_wheel', symbol: 'GOOG', asset_type: 'option', direction: 'short', option_type: 'call',
      quantity: 1, multiplier: 100, entry_price: 3.5, current_price: 3.975, current_value: -397.5, absolute_value: 397.5,
      unrealized_profit: -47.5, opened_on: '2026-09-14', expiration: '2026-10-02', strike: 360, status: 'open', closed_on: null,
      exit_price: null, realized_profit: null, quote_source: 'ibkr_statement', quote_as_of: '2026-09-14', quote_status: 'updated', last_error: null,
      linked_position_id: 7,
    }
    const closedCall: OtherHolding = {
      ...leapsCall,
      id: 17,
      status: 'closed',
      current_price: null,
      current_value: null,
      unrealized_profit: null,
      closed_on: '2026-09-20',
      exit_price: 2.3,
      realized_profit: 120,
    }
    const googPosition = position({ id: 7, symbol: 'GOOG', leaps_category: 'club' })
    render(<MemoryRouter><LeapsPage market={market} positions={[googPosition]} portfolio={portfolio} leapsCalls={[leapsCall, closedCall]} /></MemoryRouter>)
    showHoldingsTab()

    const register = screen.getByRole('region', { name: '万亿俱乐部当前持仓' })
    const cluster = within(register).getByRole('region', { name: 'GOOG 策略簇' })
    expect(within(cluster).getByRole('article', { name: 'LEAPS 持仓 7' })).toBeInTheDocument()
    expect(within(cluster).getByRole('article', { name: 'GOOG PMCC Short Call 18' })).toBeInTheDocument()
    expect(within(cluster).getByText('PMCC Short Call')).toBeInTheDocument()
    expect(within(cluster).getByRole('article', { name: 'GOOG PMCC Short Call 18' })).toHaveTextContent('关联 Long Call #7')
    expect(within(cluster).getByRole('region', { name: 'PMCC Short Call' })).toHaveTextContent(/累计已实现盈亏\s*\$120.00/)
  })

  it('keeps Eli Lilly and Berkshire out of the trillion-club register', () => {
    const excludedPositions = [
      position({ id: 31, symbol: 'LLY', leaps_category: 'club' }),
      position({ id: 32, symbol: 'BRK.B', leaps_category: 'club' }),
    ]
    const excludedCalls: OtherHolding[] = [
      {
        id: 33, category: 'leaps_call_wheel', symbol: 'LLY', asset_type: 'option', direction: 'short', option_type: 'call',
        quantity: 1, multiplier: 100, entry_price: 3, current_price: 3.5, current_value: -350, absolute_value: 350,
        unrealized_profit: -50, opened_on: '2026-09-14', expiration: '2026-10-02', strike: 900, status: 'open', closed_on: null,
        exit_price: null, realized_profit: null, quote_source: 'ibkr_statement', quote_as_of: '2026-09-14', quote_status: 'updated', last_error: null,
        linked_position_id: 31,
      },
      {
        id: 34, category: 'leaps_call_wheel', symbol: 'BRK-B', asset_type: 'option', direction: 'short', option_type: 'call',
        quantity: 1, multiplier: 100, entry_price: 3, current_price: 3.5, current_value: -350, absolute_value: 350,
        unrealized_profit: -50, opened_on: '2026-09-14', expiration: '2026-10-02', strike: 500, status: 'open', closed_on: null,
        exit_price: null, realized_profit: null, quote_source: 'ibkr_statement', quote_as_of: '2026-09-14', quote_status: 'updated', last_error: null,
        linked_position_id: 32,
      },
    ]
    render(<MemoryRouter><LeapsPage market={market} positions={excludedPositions} portfolio={portfolio} leapsCalls={excludedCalls} /></MemoryRouter>)
    showHoldingsTab()

    const register = screen.getByRole('region', { name: '万亿俱乐部当前持仓' })
    expect(within(register).getByText('尚无万亿俱乐部 Long Call 持仓')).toBeInTheDocument()
    expect(within(register).queryByRole('article', { name: 'LEAPS 持仓 31' })).not.toBeInTheDocument()
    expect(within(register).queryByRole('article', { name: 'LEAPS 持仓 32' })).not.toBeInTheDocument()
    expect(within(register).queryByRole('article', { name: /LLY PMCC Short Call/ })).not.toBeInTheDocument()
    expect(within(register).queryByRole('article', { name: /BRK-B PMCC Short Call/ })).not.toBeInTheDocument()
  })

  it('switches between the stock signal list and current holdings', () => {
    render(<MemoryRouter><LeapsPage market={market} positions={[]} portfolio={portfolio} /></MemoryRouter>)

    expect(screen.getByRole('region', { name: 'LEAPS 股票列表' })).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /QQQ.*Invesco QQQ/ })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'QQQ / QLD 当前持仓' })).not.toBeInTheDocument()

    showHoldingsTab()
    expect(screen.getByRole('region', { name: 'QQQ / QLD 当前持仓' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '万亿俱乐部 LEAPS' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: /股票列表/ }))
    expect(screen.getByRole('region', { name: 'LEAPS 股票列表' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'QQQ / QLD 当前持仓' })).not.toBeInTheDocument()
  })

  it('shows the stock signal list without a separate slot capacity panel', () => {
    render(<MemoryRouter><LeapsPage market={market} positions={[]} portfolio={portfolio} /></MemoryRouter>)

    const list = screen.getByRole('region', { name: 'LEAPS 股票列表' })
    const qqqRow = within(list).getByRole('row', { name: /QQQ.*Invesco QQQ/ })
    expect(within(qqqRow).getByText('$494.00')).toBeInTheDocument()
    expect(within(qqqRow).getByText('-1.20%')).toBeInTheDocument()
    expect(within(qqqRow).getByText('（+9.78%）')).toBeInTheDocument()
    expect(within(list).getByRole('columnheader', { name: /^当前价$/ })).toBeInTheDocument()
    expect(within(list).queryByRole('columnheader', { name: /^MA200$/ })).not.toBeInTheDocument()
    expect(within(qqqRow).getByText('42.0')).toBeInTheDocument()
    expect(within(list).queryByRole('columnheader', { name: 'LEAPS 信号' })).not.toBeInTheDocument()
    expect(within(list).getByRole('columnheader', { name: '说明' })).toBeInTheDocument()
    expect(within(list).getByRole('columnheader', { name: /^IV$/ })).toBeInTheDocument()
    expect(within(list).queryByRole('columnheader', { name: '前一日 IV' })).not.toBeInTheDocument()
    expect(within(qqqRow).getByTitle('全部入场条件已满足')).toHaveTextContent('—')
    expect(qqqRow).not.toHaveTextContent('已满足：')

    expect(screen.queryByText('五槽位容量')).not.toBeInTheDocument()
    expect(screen.queryByRole('article', { name: 'LEAPS 容量槽位 1' })).not.toBeInTheDocument()
  })

  it('shows signal details without exposing manual trade forms', () => {
    render(<MemoryRouter><LeapsPage market={market} positions={[]} portfolio={portfolio} /></MemoryRouter>)

    expect(screen.queryByText('数据来源')).not.toBeInTheDocument()
    expect(screen.queryByText('IBKR 报表同步')).not.toBeInTheDocument()
    expect(screen.queryByText('Margin 缺口')).not.toBeInTheDocument()
    expect(screen.queryByText('账户现金覆盖缺口')).not.toBeInTheDocument()
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
    showHoldingsTab()

    const fifoAlert = screen.getByText(/FIFO 换仓候选：槽位 1/).closest('[role="alert"]')
    expect(fifoAlert).toBeInTheDocument()
    const holding = screen.getByRole('article', { name: 'LEAPS 持仓 7' })
    expect(holding).toHaveClass('fifo-candidate')
    expect(within(holding).getByText('FIFO 待轮动')).toBeInTheDocument()
    expect(fifoAlert).toHaveTextContent('下一份 IBKR 报表会同步槽位记录')
  })

  it('shows QQQ and QLD exit ladders without the separate exit monitor', () => {
    const positions = [
      position({ id: 11, tranche: 1, rolled_from_position_id: 5, exit_decision: { code: 'hold', actionable: false, days_held: 100, dte: 265, return_fraction: .2, target_return: .5 } }),
      position({ id: 12, tranche: 2, exit_decision: { code: 'force_exit', actionable: true, days_held: 271, dte: 94, return_fraction: -.1, target_return: null } }),
      position({ id: 13, tranche: 3, symbol: 'QLD', asset_type: 'equity', multiplier: 1, expiration: null, strike: null, entry_price: 80, current_price: 88, current_value: 88, unrealized_profit: 8, quote_bid: null, quote_ask: null, quote_last: null, quote_iv: null, exit_decision: { code: 'hold', actionable: false, days_held: 100, dte: null, return_fraction: .1, target_return: .25 } }),
      position({ id: 14, tranche: 4, symbol: 'QLD', asset_type: 'equity', multiplier: 1, expiration: null, strike: null, entry_price: 80, current_price: 88, current_value: 88, unrealized_profit: 8, quote_bid: null, quote_ask: null, quote_last: null, quote_iv: null, exit_decision: { code: 'hold', actionable: false, days_held: 150, dte: null, return_fraction: .1, target_return: .15 } }),
      position({ id: 15, tranche: 5, symbol: 'QLD', asset_type: 'equity', multiplier: 1, expiration: null, strike: null, entry_price: 80, current_price: 82, current_value: 82, unrealized_profit: 2, quote_bid: null, quote_ask: null, quote_last: null, quote_iv: null, exit_decision: { code: 'hold', actionable: false, days_held: 220, dte: null, return_fraction: .025, target_return: .05 } }),
    ]
    render(<MemoryRouter><LeapsPage market={market} positions={positions} portfolio={portfolio} /></MemoryRouter>)
    showHoldingsTab()

    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 11' })).getByText('持仓中')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 11' })).getByText('由持仓 #5 展期至当前合约')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 12' })).queryByText('退出监控')).not.toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 12' })).queryByText('持仓超过 270 天，强制平仓')).not.toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 12' })).getByText('卖出信号')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 13' })).getByText('持仓中')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 14' })).getByText('持仓中')).toBeInTheDocument()
    expect(within(screen.getByRole('article', { name: 'LEAPS 持仓 15' })).getByText('持仓中')).toBeInTheDocument()
  })

  it('shows an independent trillion-club holding without manual entry controls', () => {
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
    showHoldingsTab()

    const register = screen.getByRole('region', { name: '万亿俱乐部当前持仓' })
    const holding = within(register).getByRole('article', { name: 'LEAPS 持仓 21' })
    expect(within(holding).getByText('AAPL')).toBeInTheDocument()
    expect(screen.queryByText('数据来源')).not.toBeInTheDocument()
    expect(within(register).queryByText('$4.20T · 2026-06-30')).not.toBeInTheDocument()
    expect(within(register).queryByText('RSI 41.0')).not.toBeInTheDocument()
    expect(within(register).queryByText('IBKR 报表同步')).not.toBeInTheDocument()
    expect(within(register).queryByRole('form')).not.toBeInTheDocument()
  })

  it('shows the realized loss from the closed contract inside a rolled synthetic holding', () => {
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
    showHoldingsTab()
    const roll = screen.getByRole('group', { name: 'MSFT 展期记录 5 到 6' })
    expect(roll).not.toHaveAttribute('open')
    expect(roll.querySelector('.leaps-roll-chevron')).toBeInTheDocument()
    expect(within(roll).getByText('查看已平仓展期记录（1 笔） · 累计已实现盈亏 -$1,000.00')).toBeInTheDocument()
    expect(within(roll).getByText('2026-12-18 $400 Call')).toBeInTheDocument()
    expect(within(roll).getByText('平仓 $45.00')).toBeInTheDocument()
    expect(within(roll).getByText('已实现 -$1,000.00')).not.toHaveClass('negative')
    expect(within(roll).getByText('净支出 $500.00')).toBeInTheDocument()
  })

  it('keeps the trillion-club area focused on rules and holdings', () => {
    const baseDecision = {
      name: 'Apple', technical_eligible: false, eligible: false,
      suggested_slot: 1, suggested_amount: 0, over_shared_budget: false,
      checks: { qqq_above_ma200: true, stock_above_ma200: true, rsi_below_45: false, daily_drop: false, live_quote: true, market_cap: true, history: true, weekly_limit: true, second_entry: true },
      current_price: 300, previous_close: 300, close: 300, ma200: 270, rsi14: 50,
      market_cap: 2_000_000_000_000, market_cap_as_of: '2026-06-30', market_cap_currency: 'USD',
      open_slots: [], fifo_candidate_position_id: null, fifo_candidate_slot: null, risk_position_ids: [],
    }
    const clubMarket: MarketSnapshot = {
      ...market,
      leaps_club: {
        decisions: [{ ...baseDecision, symbol: 'AAPL', name: 'Apple', change_fraction: -.061 }],
        unavailable: [],
        exclusions: [],
      },
    }

    render(<MemoryRouter><LeapsPage market={clubMarket} positions={[]} portfolio={portfolio} /></MemoryRouter>)
    showHoldingsTab()

    const club = screen.getByRole('region', { name: '万亿俱乐部 LEAPS' })
    expect(within(club).getByText('成员维护')).toBeInTheDocument()
    expect(within(club).getByText('尚无万亿俱乐部 Long Call 持仓')).toBeInTheDocument()
    expect(within(club).queryByText('AAPL')).not.toBeInTheDocument()
  })

  it('pins QQQ and sorts trillion-club stocks by daily drop', () => {
    const clubMarket: MarketSnapshot = {
      ...market,
      leaps_club: {
        decisions: [
          clubDecision({ symbol: 'MSFT', name: 'Microsoft', change_fraction: -.045 }),
          clubDecision({ symbol: 'NVDA', name: 'NVIDIA', change_fraction: -.081 }),
          clubDecision({ symbol: 'AAPL', name: 'Apple', change_fraction: -.02 }),
        ],
        unavailable: [],
        exclusions: [],
      },
    }

    render(<MemoryRouter><LeapsPage market={clubMarket} positions={[]} portfolio={portfolio} /></MemoryRouter>)

    const rows = within(screen.getByRole('region', { name: 'LEAPS 股票列表' })).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('QQQ')
    expect(rows[2]).toHaveTextContent('DRAM')
    expect(rows[3]).toHaveTextContent('SOXX')
    expect(rows[4]).toHaveTextContent('NVDA')
    expect(rows[5]).toHaveTextContent('MSFT')
    expect(rows[6]).toHaveTextContent('AAPL')
  })
})


describe('underlying IV in the LEAPS stock list', () => {
  it.each([['pre','盘前'], ['post','盘后'], ['overnight','夜盘']])('labels actual %s quotes and shows the trade time in New York', (session, label) => {
    const value: MarketSnapshot = { ...market, leaps_watchlist: [{ symbol: 'QQQ', name: 'Invesco QQQ',
      price: 494, change_fraction: -.012, ma200: 450, rsi14: 42, source: 'ibkr', error: null, iv: null, iv_error: null,
      price_kind: 'snapshot', session, market_session: session, quality: 'delayed', market_as_of: '2026-10-14T12:00:00Z',
    }] }
    render(<MemoryRouter><LeapsPage market={value} positions={[]} portfolio={portfolio} /></MemoryRouter>)
    const row = screen.getByRole('row', { name: /QQQ.*Invesco QQQ/ })
    expect(row).toHaveTextContent(`${label} · 延迟 · 08:00`)
    expect(screen.queryByRole('region', { name: 'PMCC 合约规则' })).not.toBeInTheDocument()
  })

  it('keeps old regular quotes distinct from unavailable overnight prices', () => {
    const value: MarketSnapshot = { ...market, leaps_watchlist: [{ symbol: 'QQQ', name: 'Invesco QQQ',
      price: 494, change_fraction: -.012, ma200: 450, rsi14: 42, source: 'ibkr', error: null, iv: null, iv_error: null,
      price_kind: 'snapshot', session: 'regular', market_session: 'overnight', quality: 'closed', session_error: '夜盘暂无行情',
    }] }
    render(<MemoryRouter><LeapsPage market={value} positions={[]} portfolio={portfolio} /></MemoryRouter>)
    const row = screen.getByRole('row', { name: /QQQ.*Invesco QQQ/ })
    expect(row).toHaveTextContent('最近日盘成交 · 冻结')
    expect(row).toHaveTextContent('夜盘报价暂缺')
  })
  it.each([
    [.25, .25, '25.00%', '↑ +25.00%'],
    [.18, -.1, '18.00%', '↓ -10.00%'],
    [.2, 0, '20.00%', '0.00%'],
  ])('shows latest IV date and retains the relative change without a previous IV column for %s', (latest, change, formattedIv, formattedChange) => {
    const value: MarketSnapshot = { ...market, leaps_watchlist: [{
      symbol: 'QQQ', name: 'Invesco QQQ', price: 494, change_fraction: -.012, ma200: 450, rsi14: 42, source: 'ibkr', error: null, iv_error: null,
      iv: { symbol: 'QQQ', latest: { as_of: '2026-10-13', value: latest }, previous: { as_of: '2026-10-12', value: .2 }, change_fraction: change, source: 'ibkr', fetched_at: '2026-10-14T10:00:00Z' },
    }] }
    render(<MemoryRouter><LeapsPage market={value} positions={[]} portfolio={portfolio} /></MemoryRouter>)
    const row = screen.getByRole('row', { name: /QQQ.*Invesco QQQ/ })
    expect(within(row).getAllByText(formattedIv).length).toBeGreaterThan(0)
    expect(within(row).getByText(formattedChange)).toBeInTheDocument()
    expect(within(row).getByText('2026-10-13')).toBeInTheDocument()
    expect(within(row).queryByText('2026-10-12')).not.toBeInTheDocument()
    expect(within(row).queryByText('2026-10-14')).not.toBeInTheDocument()
    expect(within(row).getByText(formattedChange)).toHaveClass(change > 0 ? 'positive' : change < 0 ? 'negative' : 'leaps-iv-change')
  })

  it('shows DRAM price, RSI and IV while marking an unavailable MA200', () => {
    const value: MarketSnapshot = { ...market, leaps_watchlist: [{
      symbol: 'DRAM', name: 'Roundhill Memory ETF', price: 55, change_fraction: .03, ma200: null, rsi14: 62, completed_sessions: 134, source: 'ibkr', error: null, iv_error: null,
      iv: { symbol: 'DRAM', latest: { as_of: '2026-10-13', value: .538 }, previous: null, change_fraction: null, source: 'ibkr', fetched_at: '2026-10-14T10:00:00Z' },
    }] }
    render(<MemoryRouter><LeapsPage market={value} positions={[]} portfolio={portfolio} /></MemoryRouter>)
    const row = screen.getByRole('row', { name: /DRAM.*Roundhill Memory ETF/ })
    expect(within(row).getByText('$55.00')).toBeInTheDocument()
    expect(within(row).getByText('62.0')).toBeInTheDocument()
    expect(within(row).getByText('53.80%')).toBeInTheDocument()
    expect(within(row).getByTitle('仅有 134 个完成交易日，MA200 需要 200 日')).toHaveTextContent('MA200 暂缺')
    expect(within(row).getByText(/未满足：MA200 数据不足/)).toBeInTheDocument()
  })
})
