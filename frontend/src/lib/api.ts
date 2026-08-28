import type {
  DistributionRecommendation,
  IbkrAutoImportResult,
  IbkrImportHistoryRow,
  IbkrImportPreview,
  LedgerEvent,
  MarketSnapshot,
  OtherHoldingListing,
  PortfolioSummary,
  Position,
  ProfitLedgerSnapshot,
  RebalancingSnapshot,
  Signal,
  WheelOverview,
} from './types'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: '请求失败' }))
    throw new Error(payload.detail || `请求失败 (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  portfolio: () => request<PortfolioSummary>('/portfolio/summary'),
  initialize: (payload: unknown) => request<PortfolioSummary>('/portfolio/initialize', { method: 'POST', body: JSON.stringify(payload) }),
  refresh: () => request<MarketSnapshot>('/market/refresh', { method: 'POST' }),
  wheelOverview: () => request<WheelOverview>('/wheel/overview'),
  positions: (includeClosed = false) => request<Position[]>(`/positions${includeClosed ? '?include_closed=true' : ''}`),
  otherHoldings: (includeClosed = false) => request<OtherHoldingListing>(`/other-holdings${includeClosed ? '?include_closed=true' : ''}`),
  profitLedger: () => request<ProfitLedgerSnapshot>('/profit-ledger'),
  rebalancing: (asOf?: string) => request<RebalancingSnapshot>(`/rebalancing${asOf ? `?as_of=${asOf}` : ''}`),
  evaluateRebalancing: (date: string) => request<RebalancingSnapshot>('/rebalancing/evaluate', { method: 'POST', body: JSON.stringify({ date }) }),
  signals: (includeAcknowledged = false) => request<Signal[]>(`/signals${includeAcknowledged ? '?include_acknowledged=true' : ''}`),
  events: () => request<LedgerEvent[]>('/ledger/events'),
  ibkrPreview: (payload: { filename: string; content: string }) => request<IbkrImportPreview>('/imports/ibkr/preview', { method: 'POST', body: JSON.stringify(payload) }),
  ibkrConfirm: (payload: unknown) => request<{ imported: number }>('/imports/ibkr/confirm', { method: 'POST', body: JSON.stringify(payload) }),
  ibkrAutoImport: (payload: { filename: string; content: string }) => request<IbkrAutoImportResult>('/imports/ibkr/auto', { method: 'POST', body: JSON.stringify(payload) }),
  ibkrHistory: () => request<IbkrImportHistoryRow[]>('/imports/ibkr/history'),
  post: <T>(path: string, payload: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(payload) }),
  patch: <T>(path: string, payload: unknown) => request<T>(path, { method: 'PATCH', body: JSON.stringify(payload) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  redistribute: (amount: number) => request<DistributionRecommendation>('/portfolio/redistribution', {
    method: 'POST',
    body: JSON.stringify({ distributable_profit: amount }),
  }),
}
