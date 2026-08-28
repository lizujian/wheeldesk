import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { PortfolioSummary } from '../lib/types'

const COLORS: Record<string, string> = {
  core: '#276a9b',
  cash: '#d39b2c',
  wheel: '#138369',
  leaps: '#7b55a6',
  options: '#138369',
  unallocated: '#9aa19c',
}

const LABELS: Record<string, string> = {
  core: 'BRK.B 核心仓',
  cash: '现金储备',
  wheel: 'TQQQ 车轮',
  leaps: 'QQQ LEAPS',
  options: '期权策略共享池',
  unallocated: '待分配',
}

export function AllocationChart({ portfolio }: { portfolio: PortfolioSummary }) {
  const balances = portfolio.balances
  const data = Object.entries({
    core: balances?.core ?? 0,
    cash: balances?.cash ?? 0,
    options: (balances?.wheel ?? 0) + (balances?.leaps ?? 0),
    unallocated: balances?.unallocated ?? 0,
  })
    .filter(([, value]) => value > 0)
    .map(([key, value]) => ({ key, name: LABELS[key], value }))
  return (
    <div className="allocation-visual" aria-label="资产配比环形图">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius="67%" outerRadius="91%" paddingAngle={2} stroke="none">
            {data.map((entry) => <Cell key={entry.key} fill={COLORS[entry.key]} />)}
          </Pie>
          <Tooltip formatter={(value) => formatMoney(Number(value))} />
        </PieChart>
      </ResponsiveContainer>
      <div className="allocation-total">
        <span>总资产</span>
        <strong>{compactMoney(portfolio.total_equity ?? 0)}</strong>
      </div>
    </div>
  )
}

export function formatMoney(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(value)
}

function compactMoney(value: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact' }).format(value)
}
