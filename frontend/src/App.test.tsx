import { act, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode } from 'react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App, { MARKET_CACHE_KEY, mergeMarketSnapshot, selectPmccCalls } from './App'
import { AppShell } from './components/AppShell'
import type { LeapsWatchlistEntry, MarketRefreshScope, MarketSnapshot, OtherHolding, OtherHoldingListing } from './lib/types'

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

function stubAppRequests(refresh: (scope: MarketRefreshScope) => Promise<MarketSnapshot>) {
  const refreshRequest = vi.fn(refresh)
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    let payload: unknown
    if (path.startsWith('/api/market/refresh?')) payload = await refreshRequest(new URL(path, 'http://localhost').searchParams.get('scope') as MarketRefreshScope)
    else if (path === '/api/settings/market') payload = { config_key: 'ibkr-test' }
    else if (path === '/api/portfolio/summary') payload = { initialized: false }
    else if (path === '/api/wheel/overview') payload = {
      budget: { budget: 0, target_fraction: 0, funded: 0, funding_gap: 0, funding_excess: 0, unfunded_exposure: 0, exposure: 0, available: 0, over_budget: 0, usage_fraction: null },
      recommendations: { first: 0, second: 0 }, realized_profit: 0, rounds: [],
    }
    else if (path.startsWith('/api/other-holdings')) payload = { records: [], total_value: 0, cash_equivalent_value: 0, other_value: 0, unpriced_count: 0 }
    else payload = []
    return { ok: true, status: 200, json: async () => payload } as Response
  }))
  return refreshRequest
}

describe('App', () => {
  beforeEach(() => { vi.spyOn(window, 'scrollTo').mockImplementation(() => {}); window.localStorage.clear() })
  afterEach(() => { vi.restoreAllMocks() })

  it('does not carry a previous provider watchlist into a new provider snapshot', () => {
    const previous = { ...cachedMarket, config_key: 'yahoo' }
    const next = { ...cachedMarket, config_key: 'ibkr', source: 'mixed' as const, primary_provider: 'ibkr' as const, leaps_club: { decisions: [], unavailable: [], exclusions: [] } }
    expect(mergeMarketSnapshot(previous, next).leaps_club?.decisions).toEqual([])
  })

  it('retains IV and holding occupancy on stock refresh while accepting fresh prices and full updates', () => {
    const row: LeapsWatchlistEntry = {
      symbol: 'QQQ', name: 'QQQ', price: 500, change_fraction: 0, ma200: 450, rsi14: 42,
      source: 'ibkr', error: null, iv_error: null,
      holding_occupancy: { committed: 5000, net_cash_flow: 300 },
      iv: { symbol: 'QQQ', latest: { as_of: '2026-10-13', value: .25 },
        previous: { as_of: '2026-10-12', value: .2 }, change_fraction: .25,
        source: 'ibkr', fetched_at: '2026-10-14T10:00:00Z' },
    }
    const failedRow = { ...row, symbol: 'SOXX', iv: null, iv_error: 'SOXX IV unavailable' }
    const previous: MarketSnapshot = { ...cachedMarket, config_key: 'ibkr-test', leaps_watchlist: [row, failedRow] }
    const next: MarketSnapshot = { ...previous, refresh_scope: 'stocks', leaps_watchlist: [
      { ...row, price: 510, ma200: 451, iv: null, iv_error: 'IV 仅在全量刷新时更新', holding_occupancy: null },
      { ...failedRow, price: 520, iv_error: 'IV 仅在全量刷新时更新' },
    ] }
    const merged = mergeMarketSnapshot(previous, next)
    expect(merged.leaps_watchlist?.[0]).toEqual({ ...row, price: 510, ma200: 451 })
    expect(merged.leaps_watchlist?.[1]).toEqual({ ...failedRow, price: 520 })
    expect(mergeMarketSnapshot(previous, { ...next, refresh_scope: 'full' }).leaps_watchlist?.[0].iv).toBeNull()
    expect(mergeMarketSnapshot(previous, { ...next, refresh_scope: 'full' }).leaps_watchlist?.[0].holding_occupancy).toBeNull()
    expect(mergeMarketSnapshot(previous, { ...next, config_key: 'other-connection' }).leaps_watchlist?.[0].iv).toBeNull()
    expect(mergeMarketSnapshot(previous, { ...next, config_key: 'other-connection' }).leaps_watchlist?.[0].holding_occupancy).toBeNull()
    expect(mergeMarketSnapshot(null, next).leaps_watchlist?.[0].iv).toBeNull()
  })

  it('disables actionable advice when keeping an unavailable cached watchlist', () => {
    const previous = { ...cachedMarket, leaps_club: { ...cachedMarket.leaps_club!, decisions: cachedMarket.leaps_club!.decisions.map((decision) => ({ ...decision, eligible: true, technical_eligible: true })) } }
    const next = { ...cachedMarket, leaps_club: { decisions: [], unavailable: [], exclusions: [] } }
    const merged = mergeMarketSnapshot(previous, next)
    expect(merged.stale).toBe(true)
    expect(merged.leaps_club?.decisions[0].eligible).toBe(false)
    expect(merged.leaps_club?.decisions[0].technical_eligible).toBe(false)
  })

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
      if (String(input).startsWith('/api/market/refresh?')) {
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

    await user.click(await screen.findByRole('button', { name: '刷新行情' }))

    expect(within(list).getByRole('row', { name: /AAPL/ })).toBeInTheDocument()
    expect(JSON.parse(window.localStorage.getItem(MARKET_CACHE_KEY) ?? '{}').leaps_club.decisions).toHaveLength(1)
  })

  it('refreshes once on startup in StrictMode, keeps cached data visible and still supports manual refresh', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem(MARKET_CACHE_KEY, JSON.stringify({ ...cachedMarket, config_key: 'ibkr-test' }))
    let finishRefresh!: (snapshot: MarketSnapshot) => void
    const pending = new Promise<MarketSnapshot>((resolve) => { finishRefresh = resolve })
    const refreshRequest = stubAppRequests(() => pending)
    render(<StrictMode><MemoryRouter initialEntries={['/leaps']}><App /></MemoryRouter></StrictMode>)

    expect(refreshRequest).toHaveBeenCalledTimes(1)
    expect(refreshRequest).toHaveBeenNthCalledWith(1, 'full')
    expect(screen.getByRole('button', { name: '刷新中' })).toBeDisabled()
    const list = await screen.findByRole('region', { name: 'LEAPS 股票列表' })
    expect(within(list).getByText('$500.00')).toBeInTheDocument()

    const next = { ...cachedMarket, config_key: 'ibkr-test', source: 'ibkr' as const, market: { ...cachedMarket.market, qqq: { ...cachedMarket.market.qqq, price: 505 } } }
    await act(async () => { finishRefresh(next); await pending })
    expect(await screen.findByRole('button', { name: '刷新行情' })).toBeEnabled()
    expect(within(list).getByText('$505.00')).toBeInTheDocument()
    expect(JSON.parse(window.localStorage.getItem(MARKET_CACHE_KEY) ?? '{}').market.qqq.price).toBe(505)

    const navigation = screen.getByRole('navigation', { name: '主导航' })
    await user.click(within(navigation).getByRole('link', { name: '信号' }))
    await user.click(within(navigation).getByRole('link', { name: 'LEAPS' }))
    expect(refreshRequest).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: '刷新行情' }))
    await waitFor(() => expect(refreshRequest).toHaveBeenCalledTimes(2))
    expect(refreshRequest).toHaveBeenNthCalledWith(2, 'stocks')
    expect(await screen.findByRole('button', { name: '刷新行情' })).toBeEnabled()
  })

  it('refreshes on the first visit without cache and again when the app is reloaded', async () => {
    const refreshRequest = stubAppRequests(async () => ({ ...cachedMarket, source: 'ibkr', config_key: 'ibkr-test' }))
    const firstVisit = render(<MemoryRouter initialEntries={['/leaps']}><App /></MemoryRouter>)
    const list = await screen.findByRole('region', { name: 'LEAPS 股票列表' })
    expect(await within(list).findByText('$500.00')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '刷新行情' })).toBeEnabled()
    expect(refreshRequest).toHaveBeenCalledTimes(1)
    expect(refreshRequest).toHaveBeenNthCalledWith(1, 'full')

    firstVisit.unmount()
    render(<MemoryRouter initialEntries={['/leaps']}><App /></MemoryRouter>)
    await waitFor(() => expect(refreshRequest).toHaveBeenCalledTimes(2))
    expect(refreshRequest).toHaveBeenNthCalledWith(2, 'full')
    expect(await screen.findByRole('button', { name: '刷新行情' })).toBeEnabled()
  })

  it('refreshes on navigation at the 60-second boundary and lets manual refresh restart the interval', async () => {
    const user = userEvent.setup()
    const now = vi.spyOn(Date, 'now').mockReturnValue(1_000_000)
    const request = stubAppRequests(async () => ({ ...cachedMarket, config_key: 'ibkr-test' }))
    render(<StrictMode><MemoryRouter initialEntries={['/leaps']}><App /></MemoryRouter></StrictMode>)
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新行情' })).toBeEnabled())
    const nav = screen.getByRole('navigation', { name: '主导航' })
    now.mockReturnValue(1_059_999)
    await user.click(within(nav).getByRole('link', { name: '信号' }))
    expect(request).toHaveBeenCalledTimes(1)
    now.mockReturnValue(1_060_000)
    await user.click(within(nav).getByRole('link', { name: 'LEAPS' }))
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新行情' })).toBeEnabled())
    now.mockReturnValue(1_070_000)
    await user.click(screen.getByRole('button', { name: '刷新行情' }))
    await waitFor(() => expect(request).toHaveBeenCalledTimes(3))
    await waitFor(() => expect(screen.getByRole('button', { name: '刷新行情' })).toBeEnabled())
    now.mockReturnValue(1_120_000)
    await user.click(within(nav).getByRole('link', { name: '信号' }))
    expect(request).toHaveBeenCalledTimes(3)
    now.mockReturnValue(1_130_000)
    await user.click(within(nav).getByRole('link', { name: 'LEAPS' }))
    await waitFor(() => expect(request).toHaveBeenCalledTimes(4))
    expect(request.mock.calls.map(([scope]) => scope)).toEqual(['full', 'stocks', 'stocks', 'stocks'])
  })

  it('does not duplicate a pending refresh on navigation or retry failed automatic refreshes within a minute', async () => {
    const user = userEvent.setup()
    const now = vi.spyOn(Date, 'now').mockReturnValue(1_000_000)
    let fail!: (error: Error) => void
    const pending = new Promise<MarketSnapshot>((_, reject) => { fail = reject })
    const request = stubAppRequests(() => pending)
    render(<MemoryRouter initialEntries={['/leaps']}><App /></MemoryRouter>)
    const nav = screen.getByRole('navigation', { name: '主导航' })
    now.mockReturnValue(1_060_000)
    await user.click(within(nav).getByRole('link', { name: '信号' }))
    expect(request).toHaveBeenCalledTimes(1)
    await act(async () => { fail(new Error('Gateway offline')) })
    expect(await screen.findByRole('button', { name: /Gateway offline，点击重试/ })).toHaveClass('unavailable')
    now.mockReturnValue(1_060_001)
    await user.click(within(nav).getByRole('link', { name: 'LEAPS' }))
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2))
    now.mockReturnValue(1_060_002)
    await user.click(within(nav).getByRole('link', { name: '信号' }))
    expect(request).toHaveBeenCalledTimes(2)
    expect(request.mock.calls.map(([scope]) => scope)).toEqual(['full', 'stocks'])
  })

  it('keeps stale cached data and allows retry when the automatic refresh fails', async () => {
    const user = userEvent.setup()
    window.localStorage.setItem(MARKET_CACHE_KEY, JSON.stringify({ ...cachedMarket, config_key: 'ibkr-test' }))
    const refreshRequest = stubAppRequests(async () => { throw new Error('无法连接 IB Gateway') })
    render(<MemoryRouter initialEntries={['/leaps']}><App /></MemoryRouter>)

    const sourceBadge = await screen.findByRole('button', { name: /无法连接 IB Gateway，点击重试/ })
    expect(sourceBadge).toHaveClass('source-badge', 'unavailable')
    expect(sourceBadge).toHaveAttribute('title', '无法连接 IB Gateway；点击重试')
    expect(screen.getByText('数据已过期')).toBeInTheDocument()
    const list = await screen.findByRole('region', { name: 'LEAPS 股票列表' })
    expect(within(list).getByText('$500.00')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '刷新行情' })).toBeEnabled()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    refreshRequest.mockResolvedValueOnce({ ...cachedMarket, source: 'ibkr', config_key: 'ibkr-test' })
    await user.click(sourceBadge)
    expect(refreshRequest).toHaveBeenCalledTimes(2)
    expect(refreshRequest).toHaveBeenNthCalledWith(2, 'stocks')
    await waitFor(() => expect(screen.queryByRole('button', { name: /无法连接 IB Gateway，点击重试/ })).not.toBeInTheDocument())
    const recoveredBadge = within(screen.getByRole('status', { name: '行情连接状态' })).getByText('IB Gateway')
    expect(recoveredBadge).toHaveClass('source-badge')
    expect(recoveredBadge).not.toHaveClass('unavailable')
    expect(within(list).getByText('$500.00')).toBeInTheDocument()
  })

  it('does not restore cache for an old connection when the startup refresh fails', async () => {
    window.localStorage.setItem(MARKET_CACHE_KEY, JSON.stringify({ ...cachedMarket, config_key: 'old-connection' }))
    let failRefresh!: (error: Error) => void
    const pending = new Promise<MarketSnapshot>((_, reject) => { failRefresh = reject })
    stubAppRequests(() => pending)
    render(<MemoryRouter initialEntries={['/leaps']}><App /></MemoryRouter>)
    await waitFor(() => expect(window.localStorage.getItem(MARKET_CACHE_KEY)).toBeNull())

    await act(async () => { failRefresh(new Error('无法连接 IB Gateway')) })
    expect(await screen.findByRole('button', { name: /无法连接 IB Gateway，点击重试/ })).toHaveTextContent('IB Gateway · 暂不可用')
    const list = await screen.findByRole('region', { name: 'LEAPS 股票列表' })
    expect(within(list).queryByRole('row', { name: /AAPL/ })).not.toBeInTheDocument()
    expect(within(list).queryByText('$500.00')).not.toBeInTheDocument()
  })
})
