import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { OtherHoldingListing, WheelOverview } from '../lib/types'
import { OtherHoldingsPage } from './OtherHoldingsPage'

const listing: OtherHoldingListing = {
  total_value: 34100,
  cash_equivalent_value: 30000,
  other_value: 4100,
  unpriced_count: 0,
  records: [
    {
      id: 1, category: 'cash_equivalent', symbol: 'BOXX', asset_type: 'equity', direction: 'long', option_type: null,
      quantity: 300, multiplier: 1, entry_price: 99.5, current_price: 100, current_value: 30000, absolute_value: 30000,
      unrealized_profit: 150, opened_on: '2026-01-02', expiration: null, strike: null, status: 'open', closed_on: null,
      exit_price: null, realized_profit: null, quote_source: 'ibkr_statement', quote_as_of: '2026-08-26', quote_status: 'updated', last_error: null,
    },
    {
      id: 2, category: 'other', symbol: 'AAPL', asset_type: 'option', direction: 'long', option_type: 'call',
      quantity: 1, multiplier: 100, entry_price: 35, current_price: 41, current_value: 4100, absolute_value: 4100,
      unrealized_profit: 600, opened_on: '2026-06-10', expiration: '2027-01-15', strike: 180, status: 'open', closed_on: null,
      exit_price: null, realized_profit: null, quote_source: 'yahoo', quote_as_of: '2026-08-26', quote_status: 'updated', last_error: null,
    },
    {
      id: 3, category: 'other', symbol: 'MSFT', asset_type: 'equity', direction: 'long', option_type: null,
      quantity: 5, multiplier: 1, entry_price: 400, current_price: 420, current_value: null, absolute_value: 2100,
      unrealized_profit: null, opened_on: '2026-02-01', expiration: null, strike: null, status: 'closed', closed_on: '2026-07-01',
      exit_price: 420, realized_profit: 100, quote_source: 'ibkr_statement', quote_as_of: '2026-07-01', quote_status: 'updated', last_error: null,
    },
    {
      id: 5, category: 'other', symbol: 'AVGO', asset_type: 'option', direction: 'short', option_type: 'call',
      quantity: 1, multiplier: 100, entry_price: 5.05, current_price: 5.25, current_value: -525, absolute_value: 525,
      unrealized_profit: -20, opened_on: '2026-09-22', expiration: '2026-10-23', strike: 400, status: 'open', closed_on: null,
      exit_price: null, realized_profit: null, quote_source: 'ibkr_statement', quote_as_of: '2026-09-22', quote_status: 'updated', last_error: null,
      linked_position_id: null,
    },
    {
      id: 6, category: 'other', symbol: 'AVGO', asset_type: 'option', direction: 'short', option_type: 'call',
      quantity: 1, multiplier: 100, entry_price: 4.5, current_price: null, current_value: null, absolute_value: 450,
      unrealized_profit: null, opened_on: '2026-08-01', expiration: '2026-09-18', strike: 390, status: 'closed', closed_on: '2026-09-12',
      exit_price: 1.2, realized_profit: 330, quote_source: 'ibkr_statement', quote_as_of: '2026-09-12', quote_status: 'updated', last_error: null,
      linked_position_id: 7,
    },
  ],
  leaps_call_wheels: [
    {
      id: 4, category: 'leaps_call_wheel', symbol: 'GOOG', asset_type: 'option', direction: 'short', option_type: 'call',
      quantity: 1, multiplier: 100, entry_price: 3.5, current_price: 3.975, current_value: -397.5, absolute_value: 397.5,
      unrealized_profit: -47.5, opened_on: '2026-09-14', expiration: '2026-10-02', strike: 360, status: 'open', closed_on: null,
      exit_price: null, realized_profit: null, quote_source: 'ibkr_statement', quote_as_of: '2026-09-14', quote_status: 'updated', last_error: null,
      linked_position_id: 7,
    },
  ],
}

const wheel: WheelOverview = {
  budget: {
    budget: 25000, target_fraction: 0.25, funded: 25000, funding_gap: 0,
    funding_excess: 0, unfunded_exposure: 0, exposure: 0, available: 25000,
    over_budget: 0, usage_fraction: 0,
  },
  recommendations: { first: 0, second: 0 },
  realized_profit: 0,
  rounds: [],
}

const wheelWithTransition: WheelOverview = {
  ...wheel,
  rounds: [{
    id: 9, number: 3, opened_on: '2026-09-01', closed_on: null, status: 'active', realized_profit: 100,
    voided_at: null, void_reason: null,
    puts: [{
      id: 8, round_id: 9, capital_bucket: 'wheel', symbol: 'AVGO', batch_number: 1,
      trade_date: '2026-09-01', expiration: '2026-10-23', strike: 400, premium: 5,
      quantity: 1, open_quantity: 1, assigned_contracts: 0, entry_tqqq_price: 450,
      earnings_confirmed: true, state: 'open', closed_on: null, close_premium: null,
      realized_profit: 100, collateral: 40000, opening_dte: 52, opening_annualized_return: .09,
      early_close_days: null, early_close_annualized_return: null, early_close_return_kind: null,
      quote_source: 'public', quote_bid: 4.5, quote_ask: 5, quote_last: 4.75, quote_iv: .3,
      quote_as_of: '2026-09-23', theoretical_low: null, theoretical_base: null, theoretical_high: null,
      captured_fraction: null, early_close_code: null, early_close_message: null, voided_at: null,
      void_reason: null, roll_count: 1,
      rolled_from: {
        from_put_id: 7, to_put_id: 8, rolled_on: '2026-09-10', from_expiration: '2026-09-18',
        from_strike: 390, to_expiration: '2026-10-23', to_strike: 400, buyback_premium: 4,
        new_premium: 5, quantity: 1, net_credit: 100, previous_realized_profit: 100,
      },
      rolled_to: null, share_lots: [],
    }],
  }],
}

describe('other holdings page', () => {
  it('shows BOXX as cash equivalent and has no manual entry form', () => {
    render(<OtherHoldingsPage listing={listing} />)

    expect(screen.getByText('BOXX 现金等价物')).toBeInTheDocument()
    expect(screen.getAllByText('$30,000.00')).toHaveLength(2)
    expect(screen.getByRole('row', { name: 'BOXX' })).toBeInTheDocument()
    expect(screen.getByRole('row', { name: 'AAPL 2027-01-15 $180 Call' })).toBeInTheDocument()
    expect(screen.queryByRole('row', { name: /GOOG/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('form')).not.toBeInTheDocument()
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument()
  })

  it('switches to exit history without exposing position mutation controls', async () => {
    const user = userEvent.setup()
    render(<OtherHoldingsPage listing={listing} />)

    await user.click(screen.getByRole('button', { name: /退出记录/ }))
    expect(screen.getByRole('row', { name: 'MSFT' })).toBeInTheDocument()
    expect(screen.queryByRole('row', { name: /AVGO/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /删除/ })).not.toBeInTheDocument()
  })

  it('keeps Wheel transition puts in the current holdings report without extra sections', () => {
    render(<OtherHoldingsPage listing={listing} wheel={wheelWithTransition} pmccSymbols={['AVGO']} />)

    expect(screen.getByRole('heading', { name: '其他持仓与过渡仓' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Wheel 过渡仓' })).not.toBeInTheDocument()
    expect(screen.queryByRole('article', { name: 'GOOG Sell Call #4' })).not.toBeInTheDocument()
    expect(screen.queryByRole('article', { name: 'AVGO Sell Call #5' })).not.toBeInTheDocument()
    expect(screen.queryAllByText(/权利金总额/)).toHaveLength(1)
    expect(screen.queryByText('PMCC Short Call')).not.toBeInTheDocument()
    expect(screen.queryByRole('row', { name: 'AVGO 2026-10-23 $400 Call' })).not.toBeInTheDocument()
    expect(screen.queryByText('Sell Put 开仓条件')).not.toBeInTheDocument()
    expect(screen.getByRole('row', { name: 'Wheel 过渡仓 AVGO Sell Put #8' })).toBeInTheDocument()
    const transitionRow = screen.getByRole('row', { name: 'Wheel 过渡仓 AVGO Sell Put #8' })
    expect(transitionRow).toHaveTextContent('当前担保 $40,000.00')
    expect(transitionRow).toHaveTextContent('共收 $600.00')
    expect(screen.queryByText('LIVE TRANSITION REGISTER')).not.toBeInTheDocument()
    expect(screen.queryByRole('article', { name: /个股策略簇/ })).not.toBeInTheDocument()
  })
})
