import { AlertTriangle, ShieldAlert } from 'lucide-react'
import type { RiskDecision } from '../lib/types'

export function SignalBanner({ risk }: { risk: RiskDecision }) {
  if (risk.severity !== 'critical') return null
  return (
    <div className="risk-banner" role="alert">
      <ShieldAlert size={22} aria-hidden="true" />
      <div>
        <strong>高危 · QQQ 连续两日跌破 MA200</strong>
        <p>{risk.message}</p>
        {risk.defensive_cc_required_if_holding && (
          <span><AlertTriangle size={14} />继续持股时必须使用近价或价内 Covered Call 防御</span>
        )}
      </div>
    </div>
  )
}
