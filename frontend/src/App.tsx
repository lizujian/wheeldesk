import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { SignalBanner } from './components/SignalBanner'
import { MarketDataNotice } from './components/MarketDataNotice'
import { api } from './lib/api'
import type { MarketRefreshScope, MarketSnapshot, OtherHolding, OtherHoldingListing, PortfolioSummary, Position, Signal, WheelOverview } from './lib/types'

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
export const MARKET_CACHE_KEY = 'wheeldesk.market-snapshot.v2'
const AUTOMATIC_REFRESH_INTERVAL_MS = 60_000

function readCachedMarket(): MarketSnapshot | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(MARKET_CACHE_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!isRecord(parsed) || !isRecord(parsed.market) || !isRecord(parsed.market.qqq)) return null
    return staleSnapshot(parsed as unknown as MarketSnapshot)
  } catch {
    return null
  }
}

function writeCachedMarket(snapshot: MarketSnapshot) {
  try { window.localStorage.setItem(MARKET_CACHE_KEY, JSON.stringify(snapshot)) } catch { /* localStorage may be unavailable */ }
}

export function mergeMarketSnapshot(previous: MarketSnapshot | null, next: MarketSnapshot): MarketSnapshot {
  if (previous?.config_key !== next.config_key) return next
  const previousRows = new Map(previous?.leaps_watchlist?.map((row) => [row.symbol, row]))
  const merged = next.refresh_scope === 'stocks'
    ? { ...next, leaps_watchlist: next.leaps_watchlist?.map((row) => {
      const previousRow = previousRows.get(row.symbol)
      return previousRow ? { ...row, iv: previousRow.iv, iv_error: previousRow.iv_error, holding_occupancy: previousRow.holding_occupancy } : row
    }) }
    : next
  const previousClub = previous?.leaps_club
  const nextClub = merged.leaps_club
  if (!previousClub?.decisions.length || nextClub?.decisions.length) return merged

  return {
    ...merged,
    stale: true,
    leaps_club: nextClub
      ? { ...nextClub, decisions: staleSnapshot(previous!).leaps_club!.decisions }
      : staleSnapshot(previous!).leaps_club,
  }
}

function staleSnapshot(snapshot: MarketSnapshot): MarketSnapshot {
  return {
    ...snapshot, stale: true,
    leaps: snapshot.leaps.map((decision) => ({ ...decision, eligible: false, checks: { ...decision.checks, live_quote: false } })),
    leaps_session: snapshot.leaps_session ? { ...snapshot.leaps_session, available: false } : undefined,
    leaps_fifo: snapshot.leaps_fifo ? { ...snapshot.leaps_fifo, required: false } : undefined,
    leaps_technical_ready: false,
    leaps_club: snapshot.leaps_club ? { ...snapshot.leaps_club, decisions: snapshot.leaps_club.decisions.map((decision) => ({ ...decision, eligible: false, technical_eligible: false, checks: { ...decision.checks, live_quote: false } })) } : undefined,
    leaps_etfs: snapshot.leaps_etfs ? { ...snapshot.leaps_etfs, decisions: snapshot.leaps_etfs.decisions.map((decision) => ({ ...decision, eligible: false, technical_eligible: false, checks: { ...decision.checks, live_quote: false } })) } : undefined,
    wheel: { ...snapshot.wheel, eligible: false },
    wheel_club: snapshot.wheel_club ? { ...snapshot.wheel_club, decisions: snapshot.wheel_club.decisions.map((decision) => ({ ...decision, eligible: false, technical_eligible: false })) } : undefined,
    core: snapshot.core ? { ...snapshot.core, recommendation: snapshot.core.recommendation ? { ...snapshot.core.recommendation, actionable: false } : null, assets: (snapshot.core.assets ?? []).map((asset) => ({ ...asset, actionable: false })), sell_put: snapshot.core.sell_put ? { ...snapshot.core.sell_put, actionable: false } : undefined, rotation: { ...snapshot.core.rotation, actionable: false } } : undefined,
    pmcc: snapshot.pmcc ? { ...snapshot.pmcc, entry: snapshot.pmcc.entry ? { ...snapshot.pmcc.entry, qqq: { ...snapshot.pmcc.entry.qqq, eligible: false }, individual: { ...snapshot.pmcc.entry.individual, eligible_symbols: [] } } : undefined } : undefined,
  }
}

export function selectPmccCalls(listing: OtherHoldingListing): OtherHolding[] {
  return [...new Map([
    ...(listing.leaps_call_wheels ?? []),
    ...listing.records.filter((record) =>
      record.asset_type === 'option'
      && record.direction === 'short'
      && record.option_type === 'call'
      && record.linked_position_id != null),
  ].map((call) => [call.id, call])).values()]
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
  const [marketError, setMarketError] = useState('')
  const lastAutomaticPath = useRef<string | null>(null)
  const lastRefreshStartedAt = useRef<number | null>(null)
  const refreshInFlight = useRef(false)

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
  useEffect(() => {
    void api.marketSettings().then((settings) => {
      setMarket((previous) => {
        if (previous?.config_key && previous.config_key !== settings.config_key) { clearCachedMarket(); return null }
        return previous
      })
    }).catch(() => { /* offline cache remains visibly stale */ })
  }, [])
  const refresh = useCallback(async (scope: MarketRefreshScope = 'stocks') => {
    if (refreshInFlight.current) return
    refreshInFlight.current = true
    lastRefreshStartedAt.current = Date.now()
    setRefreshing(true)
    try {
      const nextMarket = mergeMarketSnapshot(market, await api.refresh(scope))
      setMarket(nextMarket)
      writeCachedMarket(nextMarket)
      setMarketError('')
      await load()
    } catch (reason) {
      setMarket((previous) => previous ? staleSnapshot(previous) : null)
      await load()
      setMarketError(reason instanceof Error ? reason.message : '行情暂时无法刷新，请稍后重试')
    } finally {
      refreshInFlight.current = false
      setRefreshing(false)
    }
  }, [load, market])
  useEffect(() => {
    if (lastAutomaticPath.current === pathname) return
    const firstVisit = lastAutomaticPath.current === null
    lastAutomaticPath.current = pathname
    if (firstVisit || lastRefreshStartedAt.current === null || Date.now() - lastRefreshStartedAt.current >= AUTOMATIC_REFRESH_INTERVAL_MS) {
      void refresh(firstVisit ? 'full' : 'stocks')
    }
  }, [pathname, refresh])
  const resetAll = async () => { try { await api.post('/system/reset', { confirmation: 'RESET' }); clearCachedMarket(); setMarket(null); await load(); setError('') } catch (reason) { setError(reason instanceof Error ? reason.message : '重置失败'); throw reason } }
  const activeSignals = signals.filter((signal) => !signal.acknowledged)
  const criticalSignalCount = activeSignals.filter((signal) => signal.severity === 'critical').length
  const pmccCalls = selectPmccCalls(otherHoldings)
  return (
    <AppShell market={market} marketError={marketError} refreshing={refreshing} onRefresh={() => void refresh()} signalCount={activeSignals.length} criticalSignalCount={criticalSignalCount}>
      {error && <div className="error-toast" role="alert">{error}<button onClick={() => setError('')}>关闭</button></div>}
      <MarketDataNotice errors={market?.errors} />
      {market && <SignalBanner risk={market.risk} />}
      <Suspense fallback={<div className="page-loading">正在加载...</div>}><Routes>
        <Route path="/" element={<OverviewPage portfolio={portfolio} onInitialize={async (payload) => { setPortfolio(await api.initialize(payload)); await load() }} />} />
        <Route path="/core" element={<CorePage portfolio={portfolio} market={market} positions={positions} overview={wheel} />} />
        <Route path="/wheel" element={<Navigate replace to="/other-holdings" />} />
        <Route path="/wheel/history" element={<Navigate replace to="/other-holdings" />} />
        <Route path="/leaps" element={<LeapsPage market={market} positions={positionHistory} portfolio={portfolio} leapsCalls={pmccCalls} />} />
        <Route path="/other-holdings" element={<OtherHoldingsPage listing={otherHoldings} wheel={wheel} />} />
        <Route path="/imports/ibkr" element={<IbkrImportPage onImported={load} />} />
        <Route path="/signals" element={<SignalsPage signals={signals} onAcknowledge={async (id) => { await api.post(`/signals/${id}/acknowledge`, {}); await load() }} />} />
        <Route path="/settings" element={<SettingsPage portfolio={portfolio} market={market} onReset={resetAll} onMarketSettingsSaved={() => { clearCachedMarket(); setMarket(null); lastRefreshStartedAt.current = null }} />} />
      </Routes></Suspense>
    </AppShell>
  )
}
