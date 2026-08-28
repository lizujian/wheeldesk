import { useState } from 'react'
import { AlertTriangle, Database, HardDrive, RefreshCw, ShieldCheck, Trash2, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { MarketSnapshot, PortfolioSummary } from '../lib/types'

export function SettingsPage({ portfolio, market, onReset }: {
  portfolio: PortfolioSummary
  market: MarketSnapshot | null
  onReset: () => Promise<void>
}) {
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const [confirmation, setConfirmation] = useState('')
  const [resetting, setResetting] = useState(false)

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
      <div><Database size={20} /><span><strong>行情来源</strong><small>Yahoo Finance，失败时切换到明确标记的模拟数据</small></span><em>{market?.source === 'sample' ? '模拟数据' : '公开行情'}</em></div>
      <div><RefreshCw size={20} /><span><strong>刷新方式</strong><small>仅手动刷新，不运行后台定时任务</small></span><em>手动</em></div>
      <div><ShieldCheck size={20} /><span><strong>交易权限</strong><small>只做提示和统计，不连接券商下单</small></span><em>只读决策</em></div>
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
