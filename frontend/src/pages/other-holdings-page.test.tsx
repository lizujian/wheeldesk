import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { OtherHoldingListing } from '../lib/types'
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
    expect(screen.queryByRole('button', { name: /删除/ })).not.toBeInTheDocument()
  })
})
