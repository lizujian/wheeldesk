import { useEffect, useState } from 'react'
import { AlertTriangle, Database, HardDrive, RefreshCw, ShieldCheck, Trash2, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { IbkrConnectionStatus, MarketSettings, MarketSnapshot, PortfolioSummary } from '../lib/types'
import { api } from '../lib/api'
import './SettingsPage.css'

export function SettingsPage({ portfolio, market, onReset, onMarketSettingsSaved }: {
  portfolio: PortfolioSummary
  market: MarketSnapshot | null
  onReset: () => Promise<void>
  onMarketSettingsSaved?: (settings: MarketSettings) => void
}) {
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const [resetting, setResetting] = useState(false)
  const [settings, setSettings] = useState<MarketSettings | null>(null)
  const [clubSymbols, setClubSymbols] = useState('')
  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState('4001')
  const [clientId, setClientId] = useState('71')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [status, setStatus] = useState<IbkrConnectionStatus | null>(null)
  const [settingsMessage, setSettingsMessage] = useState('')
  const [settingsError, setSettingsError] = useState('')

  useEffect(() => {
    let active = true
    api.marketSettings().then((value) => {
      if (!active) return
      setSettings(value); setClubSymbols(value.club_symbols.join(', '))
      setHost(value.ibkr_host ?? '127.0.0.1'); setPort(String(value.ibkr_port ?? 4001))
      setClientId(String(value.ibkr_client_id ?? 71))
    }).catch((error: unknown) => { if (active) setSettingsError(error instanceof Error ? error.message : '无法读取行情设置') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  useEffect(() => { setStatus(null); setSettingsMessage('') }, [host, port, clientId])
  const payload = { provider: 'ibkr' as const, ibkr_host: host.trim() || null, ibkr_port: port ? Number(port) : null, ibkr_client_id: Number(clientId), club_symbols: clubSymbols.split(/[\s,，;；]+/).filter(Boolean) }
  const save = async () => {
    setSaving(true); setSettingsError(''); setSettingsMessage('')
    try {
      const value = await api.saveMarketSettings(payload)
      setSettings(value)
      setClubSymbols(value.club_symbols.join(', '))
      setSettingsMessage('已保存。股票、期权和 VIX 均使用 IB Gateway，请手动刷新行情。')
      onMarketSettingsSaved?.(value)
    } catch (error) { setSettingsError(error instanceof Error ? error.message : '保存失败') }
    finally { setSaving(false) }
  }
  const testConnection = async () => {
    setTesting(true); setStatus(null); setSettingsError('')
    try { setStatus(await api.testIbkrConnection(payload)) }
    catch (error) { setSettingsError(error instanceof Error ? error.message : '连接检查失败') }
    finally { setTesting(false) }
  }

  const closeDialog = () => {
    if (resetting) return
    setConfirming(false)
    setConfirmation('')
  }

  const resetAll = async () => {
    if (confirmation !== 'RESET') return
    setResetting(true)
    try {
      await onReset()
      setConfirming(false)
      setConfirmation('')
      navigate('/')
    } finally {
      setResetting(false)
    }
  }

  return <div className="page-stack">
    <div className="page-heading"><div><p className="eyebrow">LOCAL SETTINGS</p><h1>系统设置</h1></div></div>
    <section className="settings-list">
      <div><HardDrive size={20} /><span><strong>运行模式</strong><small>本机单用户 · SQLite</small></span><em>已启用</em></div>
      <div><Database size={20} /><span><strong>行情来源</strong><small>股票、ETF、期权与 VIX 统一读取 IB Gateway</small></span><em>{settings?.configured ? 'IB Gateway' : '待配置'}{market?.stale ? ' · 旧快照' : ''}</em></div>
      <div><RefreshCw size={20} /><span><strong>刷新方式</strong><small>仅手动刷新，不运行后台定时任务</small></span><em>手动</em></div>
      <div><ShieldCheck size={20} /><span><strong>交易权限</strong><small>只做提示和统计，不连接券商下单</small></span><em>只读决策</em></div>
    </section>
    <section className="market-settings" aria-label="行情连接设置">
      <div className="section-title"><div><p>MARKET DATA</p><h2>行情连接</h2></div><span>保存后手动刷新生效</span></div>
      <form onSubmit={(event) => { event.preventDefault(); void save() }}>
        <div className="gateway-fields">
          <label>IB Gateway 地址<input value={host} onChange={(event) => setHost(event.target.value)} placeholder="127.0.0.1" autoComplete="off" disabled={loading || saving || testing} /></label>
          <label>IB Gateway 端口<input type="number" min="1" max="65535" value={port} onChange={(event) => setPort(event.target.value)} placeholder="4001" disabled={loading || saving || testing} /></label>
        </div>
        <label>Client ID<input type="number" min="1" max="2147483647" value={clientId} onChange={(event) => setClientId(event.target.value)} disabled={loading || saving || testing} /></label>
        <p className="settings-help">盈透账号在 IB Gateway 或 TWS 中登录，并勾选“只读 API”。仅在手动刷新时查询，支持延迟和收市报价。连接或报价不可用时保留上次估值并提示。</p>
        <label>万亿俱乐部股票列表<textarea value={clubSymbols} onChange={(event) => setClubSymbols(event.target.value)} rows={3} placeholder="AAPL, AVGO, GOOG, NVDA" disabled={loading || saving || testing} /></label>
        <p className="settings-help">用逗号或换行分隔股票代码，由你维护成员，不查询市值。保存后刷新行情；移出列表会停止该股的入场信号，已有持仓继续保留。暂不查询财报日期，也不使用财报条件。</p>
        <div className="settings-actions"><button type="button" className="secondary-button" onClick={() => void testConnection()} disabled={loading || testing || saving || !host || !port}>{testing ? '正在检查连接…' : '测试 IB Gateway 连接'}</button><button type="submit" className="primary-button" disabled={loading || saving || testing}>{saving ? '正在保存…' : '保存行情设置'}</button></div>
      </form>
      {settingsError && <p className="settings-error" role="alert">{settingsError}</p>}
      {settingsMessage && <p className="settings-success" role="status">{settingsMessage}</p>}
      {status && <div className={`connection-result ${status.connected ? 'connected' : 'offline'}`} role="status">
        <strong>{status.connected ? 'IB Gateway 已连接 · 只读查询' : 'IB Gateway 未连接'}</strong>
        {status.error && <p>{status.error}</p>}
        {status.connected && <dl><div><dt>API 服务版本</dt><dd>{status.server_version ?? '未知'}</dd></div><div><dt>应用连接</dt><dd>{status.client_readonly ? '只读' : '待确认'}</dd></div><div><dt>读取到的持仓</dt><dd>{status.positions_count ?? '未知'}</dd></div></dl>}
        {status.gateway_readonly && <p>{status.gateway_readonly}</p>}
        {(['qqq', 'vix'] as const).map((symbol) => { const quote = status[symbol]; return quote && <p key={symbol}>{symbol.toUpperCase()} {quote.price.toFixed(2)} · IBKR · {({ realtime: '实时行情', closed: '收市报价', delayed: '延迟行情', unknown: '时效待确认' } as Record<string, string>)[quote.quality] ?? '时效待确认'}</p> })}
        {status.warnings?.map((item) => <p key={item.symbol}>{item.error}</p>)}
        {status.quote_error && <p>{status.quote_error}</p>}
      </div>}
    </section>
    <section className="profile-band"><span>账户年龄</span><strong>{portfolio.age ?? '—'}</strong><span>基础币种</span><strong>{portfolio.currency ?? 'USD'}</strong></section>
    <section className="danger-zone">
      <div><AlertTriangle size={20} /><span><strong>重置测试数据</strong><small>清空账户、持仓、车轮周期、账本和信号，数据库结构保持不变。</small></span></div>
      <button className="danger-button" onClick={() => setConfirming(true)} disabled={!portfolio.initialized}><Trash2 size={16} />重置全部数据</button>
    </section>
    {confirming && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDialog() }}>
      <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="reset-dialog-title">
        <header><div><p className="eyebrow">DESTRUCTIVE ACTION</p><h2 id="reset-dialog-title">确认重置全部数据</h2></div><button className="icon-button" title="关闭" onClick={closeDialog} disabled={resetting}><X size={18} /></button></header>
        <div className="dialog-warning"><AlertTriangle size={20} /><p>此操作不可撤销。所有测试账户数据、交易流水和策略状态都会被永久清空。</p></div>
        <label htmlFor="reset-confirmation">输入 RESET 继续<input id="reset-confirmation" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="off" autoFocus /></label>
        <footer><button className="secondary-button" onClick={closeDialog} disabled={resetting}>取消</button><button className="danger-button" onClick={() => void resetAll()} disabled={confirmation !== 'RESET' || resetting}><Trash2 size={16} />{resetting ? '正在清空' : '永久清空数据'}</button></footer>
      </div>
    </div>}
  </div>
}
