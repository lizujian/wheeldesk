import { ReceiptText } from 'lucide-react'

import { formatMoney } from '../components/AllocationChart'
import type { LedgerEvent } from '../lib/types'

const bucketLabel: Record<string, string> = { core: '核心仓', cash: '现金储备', wheel: '期权策略共享池', leaps: '期权策略共享池', unallocated: '待分配' }
export function LedgerPage({ events }: { events: LedgerEvent[] }) {
  return <div className="page-stack"><div className="page-heading"><div><p className="eyebrow">AUDIT LEDGER</p><h1>操作流水</h1></div><span>证券交易与入金来自 IBKR 报表</span></div>
    <section className="history-section"><div className="section-title"><div><p>AUDIT TRAIL</p><h2>全部操作流水</h2></div><span>{events.length} 条</span></div>{events.length ? <div className="data-table compact">{events.map((event) => <div className="data-row" key={event.id}><strong>{eventLabel(event.event_type)}</strong><span>{bucketLabel[event.bucket] ?? event.bucket}</span><span>{event.occurred_on}</span><em className={event.amount >= 0 ? 'positive' : 'negative'}>{formatMoney(event.amount)}</em></div>)}</div> : <div className="empty-state"><ReceiptText size={22} /><p>尚无操作流水</p></div>}</section>
  </div>
}

function eventLabel(value: string) { const labels: Record<string, string> = { opening_balance: '初始资金', deposit: '新增资金', internal_transfer: '资金分配', position_open: '记录持仓', position_close: '持仓卖出', position_partial_close: '部分卖出', realized_profit_to_cash: '已实现利润进入现金', realized_loss: '已实现亏损', profit_allocation: '收益再分配', realized_posting_reversal: '结算冲销' }; return labels[value] ?? value }
