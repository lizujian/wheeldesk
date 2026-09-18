import { ChangeEvent, DragEvent, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  FileSpreadsheet,
  History,
  Import,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Upload,
  X,
} from 'lucide-react'

import { api } from '../lib/api'
import type { IbkrAutoImportResult, IbkrImportHistoryRow } from '../lib/types'
import './IbkrImportPage.css'

const actionLabels: Record<string, string> = {
  deposit: '新增入金',
  create_position: '新增持仓',
  update_position: '更新持仓',
  roll_position: '展期 LEAPS Call',
  create_unmanaged: '新增其他持仓',
  update_unmanaged: '更新其他持仓',
  create_leaps_call: '新增 LEAPS Sell Call',
  update_leaps_call: '更新 LEAPS Sell Call',
  close_leaps_call: '平仓 LEAPS Sell Call',
  create_wheel_put: '新增 Sell Put',
  update_wheel_put: '更新 Sell Put',
  roll_wheel_put: '展期 Sell Put',
  close_wheel_put: '平仓 Sell Put',
  create_wheel_call: '新增 Covered Call',
  update_wheel_call: '更新 Covered Call',
  close_wheel_call: '平仓 Covered Call',
  close_position: '平仓 LEAPS',
  close_unmanaged: '退出其他持仓',
  record_closed_unmanaged: '记录当日开平仓',
}

export function IbkrImportPage({ onImported }: { onImported: () => Promise<void> }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<IbkrAutoImportResult | null>(null)
  const [history, setHistory] = useState<IbkrImportHistoryRow[]>([])
  const [tab, setTab] = useState<'result' | 'history'>('result')
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')

  const loadHistory = async () => {
    try { setHistory(await api.ibkrHistory()) } catch { setHistory([]) }
  }
  useEffect(() => { void loadHistory() }, [])

  const importFile = async (file: File) => {
    setError('')
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError('请选择 IBKR Activity Statement CSV 文件')
      return
    }
    if (file.size > 10_000_000) {
      setError('CSV 文件不能超过 10 MB')
      return
    }
    setBusy(true)
    try {
      const content = await file.text()
      const imported = await api.ibkrAutoImport({ filename: file.name, content })
      setResult(imported)
      setTab('result')
      await Promise.all([loadHistory(), onImported()])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '报表导入失败')
    } finally {
      setBusy(false)
    }
  }

  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) void importFile(file)
    event.target.value = ''
  }
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) void importFile(file)
  }

  return <div className="page-stack import-page">
    <div className="page-heading">
      <div><p className="eyebrow">BROKER SYNC</p><h1>IBKR 报表同步</h1></div>
      <span>选择后直接写入 · 自动增量去重</span>
    </div>

    <section className="import-source-band">
      <div
        className={`import-dropzone ${dragging ? 'dragging' : ''}`}
        onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
      >
        <input ref={inputRef} type="file" accept=".csv,text/csv" onChange={pick} hidden aria-label="选择 IBKR CSV" />
        <div className="file-glyph">{busy ? <LoaderCircle className="spinning" size={25} /> : <FileSpreadsheet size={25} />}</div>
        <div className="import-source-copy">
          <strong>{busy ? '正在同步报表' : result?.filename ?? 'Activity Statement CSV'}</strong>
          <span>{busy ? '正在匹配成交、持仓与重复记录' : result ? `截止 ${result.report_as_of ?? '未知日期'} · ${result.statement_rows} 条原始数据` : '拖入文件，或从本机选择'}</span>
        </div>
        <button className="primary-button" onClick={() => inputRef.current?.click()} disabled={busy}>
          {busy ? <LoaderCircle className="spinning" size={16} /> : <Upload size={16} />}
          {busy ? '正在导入' : '选择并导入'}
        </button>
      </div>
      <div className="privacy-seal"><ShieldCheck size={21} /><span><strong>LOCAL DATABASE</strong><small>数据仅写入本机</small></span></div>
    </section>

    {error && <div className="import-message error" role="alert"><AlertTriangle size={17} /><span>{error}</span><button onClick={() => setError('')} title="关闭"><X size={15} /></button></div>}
    {result && <div className={`import-message ${result.needs_attention ? 'warning' : 'success'}`} role="status">
      {result.needs_attention ? <AlertTriangle size={17} /> : <CheckCircle2 size={17} />}
      <span>{result.imported ? `已同步 ${result.imported} 条新增记录` : '没有需要新增的记录'}；{result.unchanged} 条已一致{result.needs_attention ? `；${result.needs_attention} 条需要代码适配` : ''}。</span>
    </div>}

    <div className="segmented-control" aria-label="导入视图">
      <button className={tab === 'result' ? 'active' : ''} onClick={() => setTab('result')}><Import size={15} />本次结果</button>
      <button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}><History size={15} />导入记录</button>
    </div>

    {tab === 'result' && result && <ImportResult result={result} />}
    {tab === 'result' && !result && <section className="import-empty"><FileSpreadsheet size={28} /><strong>等待导入 IBKR 报表</strong></section>}
    {tab === 'history' && <ImportHistory rows={history} onReload={() => void loadHistory()} />}
  </div>
}

function ImportResult({ result }: { result: IbkrAutoImportResult }) {
  return <>
    <section className="import-summary" aria-label="导入汇总">
      <SummaryCell label="本次新增" value={result.imported} tone="ready" />
      <SummaryCell label="已一致 / 已导入" value={result.unchanged} tone="matched" />
      <SummaryCell label="需要适配" value={result.needs_attention} tone={result.needs_attention ? 'review' : 'matched'} />
      <SummaryCell label="原始数据" value={result.statement_rows} tone="neutral" />
    </section>

    <section className="import-register">
      <header><div className="section-title"><div><p>SYNC REGISTER</p><h2>本次写入</h2></div><span>{result.results.length} 条</span></div></header>
      {result.results.length ? <div className="import-result-table">
        <div className="result-row head"><span>标的 / 合约</span><span>处理动作</span><span>关联记录</span></div>
        {result.results.map((row) => <div className="result-row" key={row.fingerprint}>
          <strong>{row.instrument}</strong>
          <span>{actionLabels[row.action] ?? row.action}</span>
          <span>{row.entity_type ?? '-'} {row.entity_id ?? ''}</span>
        </div>)}
      </div> : <div className="import-empty compact"><CheckCircle2 size={23} /><strong>持仓与记录已经一致</strong></div>}
    </section>

    {result.notices.length > 0 && <section className="import-register import-notices">
      <header><div className="section-title"><div><p>ADAPTATION QUEUE</p><h2>需要适配</h2></div><span>{result.notices.length} 条</span></div></header>
      {result.notices.map((notice, index) => <div className="notice-row" key={`${notice.instrument}-${index}`}><AlertTriangle size={16} /><strong>{notice.instrument}</strong><span>{notice.message}</span></div>)}
    </section>}
  </>
}

function SummaryCell({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <div className={tone}><span>{label}</span><strong>{value}</strong></div>
}

function ImportHistory({ rows, onReload }: { rows: IbkrImportHistoryRow[]; onReload: () => void }) {
  return <section className="import-register import-history">
    <header><div className="section-title"><div><p>IMPORT AUDIT</p><h2>最近导入记录</h2></div><span>{rows.length} 条</span></div><button className="icon-button" onClick={onReload} title="刷新记录"><RefreshCw size={15} /></button></header>
    {rows.length ? <div className="import-history-table">
      <div className="history-row head"><span>写入时间</span><span>文件</span><span>标的</span><span>动作</span><span>关联记录</span></div>
      {rows.map((row) => <div className="history-row" key={row.id}><span>{formatDateTime(row.created_at)}</span><strong title={row.filename}>{row.filename}</strong><b>{row.instrument}</b><span>{actionLabels[row.action] ?? row.action}</span><span>{row.entity_type ?? '-'} {row.entity_id ?? ''}</span></div>)}
    </div> : <div className="import-empty"><History size={25} /><strong>尚无导入记录</strong></div>}
  </section>
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
