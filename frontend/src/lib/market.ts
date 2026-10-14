import type { MarketSnapshot, QuoteMetadata } from './types'

export function marketSourceLabel(market: MarketSnapshot) {
  if (market.source === 'sample') return '模拟数据'
  if (market.primary_provider === 'ibkr' || market.source === 'ibkr') return 'IB Gateway'
  return 'Yahoo Finance'
}

export function quoteDescription(quote: QuoteMetadata) {
  if (!quote.quote_vendor && !quote.quote_quality) return ''
  const vendor = quote.quote_vendor === 'ibkr' ? 'IBKR' : quote.quote_vendor === 'yahoo' ? 'Yahoo' : quote.quote_vendor ?? ''
  const quality = ({ realtime: '实时权限', closed: '收市报价', delayed: '延迟行情', unknown: '时效待确认', stale: '保留旧价', legacy: '公开报价' } as Record<string, string>)[quote.quote_quality ?? ''] ?? ''
  const asOf = quote.quote_market_as_of
    ? `行情时间 ${new Date(quote.quote_market_as_of).toLocaleString()}`
    : quote.quote_fetched_at ? `获取时间 ${new Date(quote.quote_fetched_at).toLocaleString()} · 盘口时间未知` : ''
  return [vendor, quality, asOf].filter(Boolean).join(' · ')
}
