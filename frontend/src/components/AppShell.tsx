import {
  Activity,
  BellRing,
  BookOpen,
  Gauge,
  HandCoins,
  FileInput,
  Layers3,
  Landmark,
  RefreshCw,
  Scale,
  Settings,
  Sparkles,
  Waypoints,
} from 'lucide-react'
import { NavLink } from 'react-router-dom'
import type { ReactNode } from 'react'
import type { MarketSnapshot } from '../lib/types'
import './AppShell.css'

const destinations = [
  ['/', '总览', Gauge],
  ['/core', '核心仓', Landmark],
  ['/wheel', '车轮', Waypoints],
  ['/leaps', 'LEAPS', Sparkles],
  ['/rebalancing', '再平衡', Scale],
  ['/profit-ledger', '收益', HandCoins],
  ['/ledger', '账本', BookOpen],
  ['/other-holdings', '其他', Layers3],
  ['/imports/ibkr', '导入', FileInput],
  ['/signals', '信号', Activity],
  ['/settings', '设置', Settings],
] as const

export function AppShell({ children, market, refreshing, onRefresh, signalCount, criticalSignalCount }: {
  children: ReactNode
  market: MarketSnapshot | null
  refreshing: boolean
  onRefresh: () => void
  signalCount: number
  criticalSignalCount: number
}) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark"><span>W</span><div><strong>WheelDesk</strong><small>本地策略台</small></div></div>
        <nav aria-label="主导航">
          {destinations.map(([path, label, Icon]) => (
            <NavLink key={path} to={path} end={path === '/'}>
              <Icon size={18} aria-hidden="true" /><span>{label}</span>{path === '/signals' && signalCount > 0 && <b className={`nav-signal-count ${criticalSignalCount ? 'critical' : ''}`}>{signalCount > 99 ? '99+' : signalCount}</b>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot"><span className="status-dot" />本机 · USD</div>
      </aside>
      <div className="work-area">
        <header className="topbar">
          <div className="mobile-brand">WheelDesk</div>
          <div className="data-state">
            {market ? (
              <><span className={`source-badge ${market.source}`}>{market.source === 'sample' ? '模拟数据' : '公开行情'}</span><span>{market.as_of}</span>{market.stale && <strong>数据已过期</strong>}</>
            ) : <span>尚未刷新行情</span>}
          </div>
          <NavLink className={`global-signal-indicator ${signalCount ? 'active' : ''} ${criticalSignalCount ? 'critical' : ''}`} to="/signals" aria-label={signalCount ? `${signalCount} 条待处理信号` : '暂无待处理信号'}>
            <BellRing size={17} aria-hidden="true" />
            <span><strong>{signalCount ? `${signalCount} 条待处理` : '信号已处理'}</strong><small>{criticalSignalCount ? `${criticalSignalCount} 条高危` : signalCount ? '点击查看建议' : '查看近期记录'}</small></span>
            {signalCount > 0 && <b>{signalCount > 99 ? '99+' : signalCount}</b>}
          </NavLink>
          <button className="primary-button" onClick={onRefresh} disabled={refreshing} title="刷新行情">
            <RefreshCw size={16} className={refreshing ? 'spinning' : ''} />{refreshing ? '刷新中' : '刷新行情'}
          </button>
        </header>
        <main>{children}</main>
      </div>
      <nav className="mobile-nav" aria-label="移动端主导航">
        {destinations.map(([path, label, Icon]) => (
          <NavLink key={path} to={path} end={path === '/'}><Icon size={18} /><span>{label}</span></NavLink>
        ))}
      </nav>
    </div>
  )
}
