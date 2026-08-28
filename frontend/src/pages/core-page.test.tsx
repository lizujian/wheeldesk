import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { CoreStrategyDecision, MarketSnapshot, PortfolioSummary, Position } from '../lib/types'
import { CorePage } from './CorePage'

const portfolio: PortfolioSummary = {
  initialized: true, age: 30, other_holdings_value: 25000, currency: 'USD', total_equity: 100000,
  balances: { core: 45000, cash: 10000, wheel: 20000, leaps: 25000, unallocated: 0 },
  targets: {
    core: { fraction: .5, amount: 50000, actual: 45000, variance: -5000 },
    cash: { fraction: .05, amount: 5000, actual: 10000, variance: 5000 },
    wheel: { fraction: .2, amount: 20000, actual: 20000, variance: 0 },
    leaps: { fraction: .25, amount: 25000, actual: 25000, variance: 0 },
  },
  capital: {
    core: { assigned: 45000, committed: 8450, available: 36550, cash_occupancy: 0 },
    cash: { total: 10000, occupied: 0, available: 10000, margin_shortfall: 0 },
    wheel: { assigned: 20000, committed: 0, available: 20000, cash_occupancy: 0 },
    leaps: { assigned: 25000, committed: 0, available: 25000, cash_occupancy: 0 },
  },
}

const brkAsset = {
  symbol: 'BRK.B' as const, current_value: 7350, price: 490, rsi14: 55, drawdown: .02,
  ma200: 460, below_ma200_two_days: false, return_20d: .08, return_126d: .18,
  code: 'monthly' as const, actionable: true, fraction: .1, strategy_amount: 4025,
  executable_amount: 4025, funding_required: 0, shares: 8.2143,
}
const vooAsset = {
  symbol: 'VOO' as const, current_value: 2400, price: 600, rsi14: 44, drawdown: .06,
  ma200: 560, below_ma200_two_days: false, return_20d: -.04, return_126d: .08,
  code: 'pullback' as const, actionable: true, fraction: .2, strategy_amount: 8050,
  executable_amount: 8050, funding_required: 0, shares: 13.4167,
}

const market: MarketSnapshot = {
  source: 'sample', as_of: '2026-07-09', stale: false,
  market: {
    qqq: { price: 510, ma20: 508, ma200: 480, rsi14: 44, bearish: true, drawdown: .1 },
    tqqq: { price: 100 }, brk_b: { price: 490 }, voo: { price: 600 }, vix: { price: 22 },
  },
  wheel: { eligible: false, checks: {}, dte_range: [30, 45], delta_range: [.2, .3], reference_strike: 87, preferred_support: null, supports: [] },
  risk: { severity: 'info', stop_required: false, defensive_cc_required_if_holding: false, message: '' },
  leaps: [],
  core: {
    mode: 'accumulating', total_target: 50000, total_value: 9750, target_gap: 40250,
    full_threshold: 49000, ratio_z: 1.2, route_confirmation_days: 3,
    rotation_confirmation_days: 0, selected_symbol: 'VOO', daily_limit_open: true,
    recommendation: { ...vooAsset, executable_amount: 8500, shares: 14.1667, cash_required: 0 },
    rotation: { code: 'waiting', actionable: false, sell_symbol: null, buy_symbol: null, amount: 0, sell_shares: 0, buy_shares: 0, return_spread: 0, defensive_half: false, cooldown_days_remaining: 0 },
    assets: [brkAsset, vooAsset], core_available: 36550, cash_available: 10000,
  },
}

const positions: Position[] = [
  { id: 1, bucket: 'core', symbol: 'BRK.B', asset_type: 'equity', quantity: 10, multiplier: 1, entry_price: 400, current_price: 420, current_value: 4200, unrealized_profit: 200, opened_on: '2026-06-01', expiration: null, strike: null, delta: null, tranche: null, status: 'open', total_loss_impact: null },
  { id: 2, bucket: 'core', symbol: 'BRK.B', asset_type: 'equity', quantity: 5, multiplier: 1, entry_price: 450, current_price: 460, current_value: 2300, unrealized_profit: 50, opened_on: '2026-07-01', expiration: null, strike: null, delta: null, tranche: null, status: 'open', total_loss_impact: null },
  { id: 3, bucket: 'core', symbol: 'VOO', asset_type: 'equity', quantity: 4, multiplier: 1, entry_price: 550, current_price: 600, current_value: 2400, unrealized_profit: 200, opened_on: '2026-07-05', expiration: null, strike: null, delta: null, tranche: null, status: 'open', total_loss_impact: null },
]

describe('core equity page', () => {
  it('shows the combined core budget and both strategy assets', () => {
    render(<CorePage portfolio={portfolio} market={market} positions={positions} />)

    expect(screen.getByText('核心仓目标预算')).toBeInTheDocument()
    expect(screen.getByText('总资产动态目标 50.0%')).toBeInTheDocument()
    expect(screen.getByText('$8,450.00')).toBeInTheDocument()
    expect(screen.getAllByText('$9,750.00').length).toBeGreaterThan(0)
    expect(screen.getByText('$40,250.00')).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'BRK.B 核心仓状态' })).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'VOO 核心仓状态' })).toHaveClass('selected')
    expect(screen.getByText('第 1 笔 · 2026-07-05')).toBeInTheDocument()
  })

  it('does not expose manual position mutation controls', () => {
    render(<CorePage portfolio={portfolio} market={market} positions={positions} />)
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /成交|删除|编辑/ })).not.toBeInTheDocument()
  })

  it('keeps rendering while a previously cached core snapshot has no relative assets', () => {
    const legacyMarket: MarketSnapshot = {
      ...market,
      core: { ...market.core!, assets: undefined } as unknown as CoreStrategyDecision,
    }
    render(<CorePage portfolio={portfolio} market={legacyMarket} positions={positions} />)

    expect(screen.getByText('刷新行情后计算两只标的的相对偏离')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '核心仓买入建议' })).toBeInTheDocument()
  })

  it('shows the routed buy amount and estimated VOO shares', () => {
    render(<CorePage portfolio={portfolio} market={market} positions={positions} />)
    const signal = screen.getByRole('region', { name: '核心仓买入建议' })
    expect(within(signal).getByText(/普通回调 · VOO/)).toBeInTheDocument()
    expect(within(signal).getByText('下一笔优先买入 VOO')).toBeInTheDocument()
    expect(within(signal).getByText('$8,500.00')).toBeInTheDocument()
    expect(within(signal).getByText('约 14.1667 股')).toBeInTheDocument()
  })

  it('shows a paired full-core rotation signal', () => {
    const fullMarket: MarketSnapshot = {
      ...market,
      core: {
        ...market.core!, mode: 'full', total_value: 50000, target_gap: 0,
        selected_symbol: null, recommendation: null, rotation_confirmation_days: 5,
        rotation: { code: 'standard', actionable: true, sell_symbol: 'BRK.B', buy_symbol: 'VOO', amount: 3000, sell_shares: 6.1224, buy_shares: 5, return_spread: .18, defensive_half: false, cooldown_days_remaining: 0 },
      },
    }
    render(<CorePage portfolio={portfolio} market={fullMarket} positions={positions} />)
    const rotation = screen.getByRole('region', { name: '核心仓满仓轮换建议' })
    expect(within(rotation).getByText('标准轮换')).toBeInTheDocument()
    expect(within(rotation).getByText('BRK.B → VOO')).toBeInTheDocument()
    expect(within(rotation).getByText('$3,000.00')).toBeInTheDocument()
  })
})
