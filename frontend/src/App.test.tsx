import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App, { MARKET_CACHE_KEY, selectPmccCalls } from './App'
import { AppShell } from './components/AppShell'
import type { MarketSnapshot, OtherHolding, OtherHoldingListing } from './lib/types'

const cachedMarket: MarketSnapshot = {
  source: 'yahoo', as_of: '2026-09-23', stale: false,
  market: {
    qqq: { price: 500, ma20: 510, ma200: 450, rsi14: 42, bearish: true, drawdown: .1 },
    tqqq: { price: 80 }, brk_b: { price: 500 }, vix: { price: 20 },
  },
  wheel: { eligible: false, checks: {}, dte_range: [30, 45], delta_range: [.2, .3], reference_strike: 70, preferred_support: null, supports: [] },
  risk: { severity: 'info', stop_required: false, defensive_cc_required_if_holding: false, message: '' },
  leaps: [{ tranche: 1, eligible: false, allocation_fraction: .2, suggested_amount: 0, checks: {} }],
  leaps_club: {
    decisions: [{
      symbol: 'AAPL', name: 'Apple', technical_eligible: false, eligible: false,
      suggested_slot: 1, suggested_amount: 0, over_shared_budget: false, checks: {},
      current_price: 290, previous_close: 300, change_fraction: -.0333, close: 290,
      ma200: 270, rsi14: 48, market_cap: 3_000_000_000_000,
      market_cap_as_of: '2026-06-30', market_cap_currency: 'USD', open_slots: [1],
      fifo_candidate_position_id: null, fifo_candidate_slot: null, risk_position_ids: [],
    }],
    unavailable: [], exclusions: [],
  },
}

describe('App', () => {
  beforeEach(() => { vi.spyOn(window, 'scrollTo').mockImplementation(() => {}); window.localStorage.clear() })

  it('selects PMCC calls by explicit strategy link instead of matching ticker', () => {
    const makeCall = (id: number, overrides: Partial<OtherHolding>): OtherHolding => ({
      id, category: 'other', symbol: 'AVGO', asset_type: 'option', direction: 'short', option_type: 'call',
      quantity: 1, multiplier: 100, entry_price: 5, current_price: 5, current_value: -500, absolute_value: 500,
      unrealized_profit: 0, opened_on: '2026-09-25', expiration: '2026-10-23', strike: 400, status: 'open',
      closed_on: null, exit_price: null, realized_profit: null, quote_source: 'ibkr_statement', quote_as_of: null,
      quote_status: 'updated', last_error: null, ...overrides,
    })
    const listing: OtherHoldingListing = {
      records: [makeCall(3, {}), makeCall(4, { linked_position_id: 31 })],
      total_value: 0, cash_equivalent_value: 0, other_value: 0, unpriced_count: 0,
      leaps_call_wheels: [
        makeCall(1, { category: 'leaps_call_wheel', linked_position_id: 31 }),
        makeCall(2, { category: 'leaps_call_wheel', linked_position_id: 32 }),
      ],
    }

    expect(selectPmccCalls(listing).map((call) => call.id)).toEqual([1, 2, 4])
  })

  it('renders the operating-console destinations without manual ledger modules', () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )

    const navigation = screen.getByRole('navigation', { name: '主导航' })
    for (const label of ['总览', '核心仓', 'LEAPS', '其他', '导入', '信号', '设置']) {
      expect(within(navigation).getByRole('link', { name: label })).toBeInTheDocument()
    }
    expect(within(navigation).queryByRole('link', { name: '再平衡' })).not.toBeInTheDocument()
    expect(within(navigation).queryByRole('link', { name: '账本' })).not.toBeInTheDocument()
    expect(within(navigation).queryByRole('link', { name: '收益' })).not.toBeInTheDocument()
    expect(within(navigation).queryByRole('link', { name: '车轮' })).not.toBeInTheDocument()
    expect(within(navigation).queryByRole('link', { name: '待退出仓' })).not.toBeInTheDocument()
  })

  it('returns the document to the top after sidebar navigation', async () => {
    const user = userEvent.setup()
    const scrollTo = vi.mocked(window.scrollTo)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )
    scrollTo.mockClear()

    const navigation = screen.getByRole('navigation', { name: '主导航' })
    await user.click(within(navigation).getByRole('link', { name: '核心仓' }))

    expect(scrollTo).toHaveBeenCalledWith(0, 0)
  })

  it('shows a global critical signal indicator in navigation and the top bar', () => {
    render(
      <MemoryRouter>
        <AppShell market={null} refreshing={false} onRefresh={() => {}} signalCount={3} criticalSignalCount={1}>
          <div>content</div>
        </AppShell>
      </MemoryRouter>,
    )

    const navigation = screen.getByRole('navigation', { name: '主导航' })
    expect(within(navigation).getByRole('link', { name: /信号\s*3/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '3 条待处理信号' })).toHaveClass('critical')
    expect(screen.getByText('1 条高危')).toBeInTheDocument()
  })

  it('restores the cached trillion-club watchlist after a browser reload', async () => {
    window.localStorage.setItem(MARKET_CACHE_KEY, JSON.stringify(cachedMarket))
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    render(
      <MemoryRouter initialEntries={['/leaps']}>
        <App />
      </MemoryRouter>,
    )

    const list = await screen.findByRole('region', { name: 'LEAPS 股票列表' })
    expect(within(list).getByRole('row', { name: /AAPL/ })).toBeInTheDocument()
  })

  it('keeps the cached trillion-club watchlist when refresh returns an empty club snapshot', async () => {
    window.localStorage.setItem(MARKET_CACHE_KEY, JSON.stringify(cachedMarket))
    const refreshedMarket: MarketSnapshot = {
      ...cachedMarket,
      as_of: '2026-09-24',
      leaps_club: { decisions: [], unavailable: [{ symbol: 'AAPL', name: 'Apple', error: '行情暂时不可用' }], exclusions: [] },
    }
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/market/refresh')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => refreshedMarket } as Response)
      }
      return Promise.reject(new Error('offline'))
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/leaps']}>
        <App />
      </MemoryRouter>,
    )

    const list = await screen.findByRole('region', { name: 'LEAPS 股票列表' })
    expect(within(list).getByRole('row', { name: /AAPL/ })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '刷新行情' }))

    expect(within(list).getByRole('row', { name: /AAPL/ })).toBeInTheDocument()
    expect(JSON.parse(window.localStorage.getItem(MARKET_CACHE_KEY) ?? '{}').leaps_club.decisions).toHaveLength(1)
  })
})
