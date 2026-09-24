import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { SignalBanner } from './components/SignalBanner'
import { api } from './lib/api'
import type { MarketSnapshot, OtherHoldingListing, PortfolioSummary, Position, Signal, WheelOverview } from './lib/types'

const OverviewPage = lazy(() => import('./pages/OverviewPage').then((module) => ({ default: module.OverviewPage })))
const CorePage = lazy(() => import('./pages/CorePage').then((module) => ({ default: module.CorePage })))
const LeapsPage = lazy(() => import('./pages/LeapsPage').then((module) => ({ default: module.LeapsPage })))
const IbkrImportPage = lazy(() => import('./pages/IbkrImportPage').then((module) => ({ default: module.IbkrImportPage })))
const OtherHoldingsPage = lazy(() => import('./pages/OtherHoldingsPage').then((module) => ({ default: module.OtherHoldingsPage })))
const SignalsPage = lazy(() => import('./pages/SignalsPage').then((module) => ({ default: module.SignalsPage })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })))

const emptyPortfolio: PortfolioSummary = { initialized: false }
const emptyWheel: WheelOverview = {
  budget: {
    budget: 0,
    target_fraction: 0,
    funded: 0,
    funding_gap: 0,
    funding_excess: 0,
    unfunded_exposure: 0,
    exposure: 0,
    available: 0,
    over_budget: 0,
    usage_fraction: null,
  },
  recommendations: { first: 0, second: 0 },
  realized_profit: 0,
  rounds: [],
}
const emptyOtherHoldings: OtherHoldingListing = { records: [], total_value: 0, cash_equivalent_value: 0, other_value: 0, unpriced_count: 0 }
export const MARKET_CACHE_KEY = 'wheeldesk.market-snapshot.v1'

function readCachedMarket(): MarketSnapshot | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(MARKET_CACHE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!isRecord(parsed) || !isRecord(parsed.market) || !isRecord(parsed.market.qqq)) return null
    return parsed as unknown as MarketSnapshot
  } catch {
    return null
  }
}

function writeCachedMarket(snapshot: MarketSnapshot) {
  try { window.localStorage.setItem(MARKET_CACHE_KEY, JSON.stringify(snapshot)) } catch { /* localStorage may be unavailable */ }
}

function clearCachedMarket() {
  try { window.localStorage.removeItem(MARKET_CACHE_KEY) } catch { /* localStorage may be unavailable */ }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export default function App() {
  const { pathname } = useLocation()
  const [portfolio, setPortfolio] = useState<PortfolioSummary>(emptyPortfolio)
  const [market, setMarket] = useState<MarketSnapshot | null>(() => readCachedMarket())
  const [wheel, setWheel] = useState<WheelOverview>(emptyWheel)
  const [positions, setPositions] = useState<Position[]>([])
  const [positionHistory, setPositionHistory] = useState<Position[]>([])
  const [signals, setSignals] = useState<Signal[]>([])
  const [otherHoldings, setOtherHoldings] = useState<OtherHoldingListing>(emptyOtherHoldings)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  useLayoutEffect(() => { window.scrollTo(0, 0) }, [pathname])

  const load = useCallback(async () => {
    try {
      const portfolioValue = await api.portfolio()
      const [wheelValue, positionsValue, positionHistoryValue, signalsValue, otherHoldingsValue] = await Promise.all([
        api.wheelOverview(), api.positions(), api.positions(true), api.signals(true), api.otherHoldings(true),
      ])
      setPortfolio(portfolioValue); setWheel(wheelValue); setPositions(positionsValue); setPositionHistory(positionHistoryValue); setSignals(signalsValue); setOtherHoldings(otherHoldingsValue); setError('')
    } catch (reason) { setError(reason instanceof Error ? reason.message : '无法连接本地服务') }
  }, [])

  useEffect(() => { void load() }, [load])
  const refresh = async () => { setRefreshing(true); try { const nextMarket = await api.refresh(); setMarket(nextMarket); writeCachedMarket(nextMarket); await load() } catch (reason) { setError(reason instanceof Error ? reason.message : '刷新失败') } finally { setRefreshing(false) } }
  const resetAll = async () => { try { await api.post('/system/reset', { confirmation: 'RESET' }); clearCachedMarket(); setMarket(null); await load(); setError('') } catch (reason) { setError(reason instanceof Error ? reason.message : '重置失败'); throw reason } }
  const activeSignals = signals.filter((signal) => !signal.acknowledged)
  const criticalSignalCount = activeSignals.filter((signal) => signal.severity === 'critical').length
  const activeLeapsSymbols = new Set(positionHistory
    .filter((position) => position.bucket === 'leaps' && position.status === 'open')
    .map((position) => position.symbol))
  const pmccCalls = [...new Map([
    ...(otherHoldings.leaps_call_wheels ?? []),
    ...otherHoldings.records.filter((record) =>
      record.asset_type === 'option'
      && record.direction === 'short'
      && record.option_type === 'call'
      && activeLeapsSymbols.has(record.symbol)),
  ].map((call) => [call.id, call])).values()]
  return (
    <AppShell market={market} refreshing={refreshing} onRefresh={() => void refresh()} signalCount={activeSignals.length} criticalSignalCount={criticalSignalCount}>
      {error && <div className="error-toast" role="alert">{error}<button onClick={() => setError('')}>关闭</button></div>}
      {market && <SignalBanner risk={market.risk} />}
      <Suspense fallback={<div className="page-loading">正在加载...</div>}><Routes>
        <Route path="/" element={<OverviewPage portfolio={portfolio} onInitialize={async (payload) => { setPortfolio(await api.initialize(payload)); await load() }} />} />
        <Route path="/core" element={<CorePage portfolio={portfolio} market={market} positions={positions} overview={wheel} />} />
        <Route path="/wheel" element={<Navigate replace to="/other-holdings" />} />
        <Route path="/wheel/history" element={<Navigate replace to="/other-holdings" />} />
        <Route path="/leaps" element={<LeapsPage market={market} positions={positionHistory} portfolio={portfolio} leapsCalls={pmccCalls} />} />
        <Route path="/other-holdings" element={<OtherHoldingsPage listing={otherHoldings} wheel={wheel} pmccSymbols={[...activeLeapsSymbols]} />} />
        <Route path="/imports/ibkr" element={<IbkrImportPage onImported={load} />} />
        <Route path="/signals" element={<SignalsPage signals={signals} onAcknowledge={async (id) => { await api.post(`/signals/${id}/acknowledge`, {}); await load() }} />} />
        <Route path="/settings" element={<SettingsPage portfolio={portfolio} market={market} onReset={resetAll} />} />
      </Routes></Suspense>
    </AppShell>
  )
}
