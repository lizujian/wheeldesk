import { AlertTriangle, ChevronDown } from 'lucide-react'

export function MarketDataNotice({ errors = [] }: {
  errors?: { symbol: string; error: string }[]
}) {
  if (!errors.length) return null

  return <details className="market-data-notice">
    <summary>
      <span className="market-notice-label" role="status">
        <AlertTriangle size={15} aria-hidden="true" />
        <strong>部分行情未更新</strong>
        <span className="market-notice-count">{errors.length} 项</span>
      </span>
      <span className="market-notice-toggle">
        <span className="market-notice-expand">查看详情</span>
        <span className="market-notice-collapse">收起详情</span>
        <ChevronDown size={14} aria-hidden="true" />
      </span>
    </summary>
    <ul className="market-notice-errors" aria-label="未更新行情明细" tabIndex={0}>
      {errors.map((item, index) => <li key={`${item.symbol}:${item.error}:${index}`}>
        <strong>{item.symbol}</strong>
        <span>{item.error}</span>
      </li>)}
    </ul>
  </details>
}
