import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { RebalancingPage } from './RebalancingPage'
import type { RebalancingSnapshot } from '../lib/types'

const snapshot: RebalancingSnapshot = {
  as_of: '2026-07-31',
  schedule: { last_rebalanced_on: null, next_review_on: '2026-07-31', due: true },
  assigned: { total: 100000, buckets: { core: 50000, cash: 10000, wheel: 32000, leaps: 8000 } },
  capital: {
    core: { assigned: 50000, committed: 50000, available: 0, cash_occupancy: 0 },
    cash: { total: 10000, occupied: 0, available: 10000, margin_shortfall: 0 },
    wheel: { assigned: 32000, committed: 0, available: 32000, cash_occupancy: 0 },
    leaps: { assigned: 8000, committed: 0, available: 8000, cash_occupancy: 0 },
    options: { assigned: 40000, committed: 0, available: 40000, cash_occupancy: 0 },
  },
  economic: {
    total: 130000,
    buckets: {
      core: { value: 80000, fraction: 0.6153846, target_fraction: 0.5, deviation: 0.1153846 },
      cash: { value: 10000, fraction: 0.0769231, target_fraction: 0.05, deviation: 0.0269231 },
      options: { value: 40000, fraction: 0.3076923, target_fraction: 0.45, deviation: -0.1423077 },
    },
    unrealized: { core: 30000, wheel: 0, leaps: 0 },
  },
  core_price: 800,
  core_symbol: 'BRK.B',
  core_decision: { code: 'sell', actionable: true, target_after_sale: 0.55, sell_amount: 8500, estimated_shares: 10.625, symbol: 'BRK.B' },
  recommendations: [
    { priority: 1, code: 'restore_cash', bucket: 'cash', amount: 3000, message: '恢复现金。' },
    { priority: 2, code: 'sell_core', bucket: 'core', amount: 8500, message: '核心仓超过硬阈值。' },
  ],
}

describe('rebalancing workbench', () => {
  it('shows due state, economic allocation, deviation bands, and read-only advice', () => {
    render(<RebalancingPage snapshot={snapshot} onEvaluate={async () => {}} onAction={async () => {}} />)

    expect(screen.getByText('本期复核已到期')).toBeInTheDocument()
    expect(screen.getByText('经济权益')).toBeInTheDocument()
    expect(screen.getByText('核心仓 +11.5 个百分点')).toBeInTheDocument()
    expect(screen.getByText('建议卖出至目标 +5 个百分点')).toBeInTheDocument()
    expect(screen.getByText('核心仓超过硬阈值。')).toBeInTheDocument()
  })

  it('evaluates a chosen date without exposing a broker fill form', async () => {
    const user = userEvent.setup()
    const onEvaluate = vi.fn().mockResolvedValue(undefined)
    const onAction = vi.fn().mockResolvedValue(undefined)
    render(<RebalancingPage snapshot={snapshot} onEvaluate={onEvaluate} onAction={onAction} />)

    await user.click(screen.getByRole('button', { name: '按当前日期评估' }))
    expect(onEvaluate).toHaveBeenCalledWith(expect.any(String))
    expect(screen.getByText('核心仓出现再平衡卖出建议')).toBeInTheDocument()
    expect(screen.getByText(/券商成交结果由下一份 IBKR 报表同步/)).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: '记录核心仓再平衡成交' })).not.toBeInTheDocument()
    expect(onAction).not.toHaveBeenCalledWith('/rebalancing/core-sale', expect.anything(), 'POST')
  })

  it('shows Wheel and LEAPS as one shared option allocation', () => {
    render(<RebalancingPage snapshot={snapshot} onEvaluate={async () => {}} onAction={async () => {}} />)

    expect(screen.getByText('期权策略共享池')).toBeInTheDocument()
    expect(screen.getByText('经济 30.8% · 目标 45.0%')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'LEAPS 策略本金过渡' })).not.toBeInTheDocument()
  })
})
