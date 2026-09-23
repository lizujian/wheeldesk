import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ProfitLedgerSnapshot } from '../lib/types'
import { ProfitLedgerPage } from './ProfitLedgerPage'

const ledger: ProfitLedgerSnapshot = {
  summary: {
    wheel_realized: 2400,
    leaps_realized: 5600,
    other_realized: 0,
    net_realized: 8000,
    allocated: 3000,
    available: 5000,
  },
  entries: [
    {
      id: 'manual:2',
      entry_type: 'allocation',
      source: 'allocation',
      occurred_on: new Date().toISOString().slice(0, 10),
      amount: -3000,
      note: '第一次再分配',
      automatic: false,
      deletable: true,
      allocations: { core: 1800, wheel: 1200 },
    },
    {
      id: 'wheel-put:1',
      entry_type: 'realized',
      source: 'wheel',
      occurred_on: '2026-07-17',
      amount: 2400,
      note: 'Sell Put #1 到期',
      automatic: true,
      deletable: false,
      allocations: {},
    },
    {
      id: 'manual:1',
      entry_type: 'realized',
      source: 'leaps',
      occurred_on: '2026-07-16',
      amount: 5600,
      note: '第一批 LEAPS 止盈',
      automatic: false,
      deletable: true,
      allocations: {},
    },
  ],
}

describe('distributable profit ledger page', () => {
  it('shows source totals, confirmed allocation, and current available balance', () => {
    render(<ProfitLedgerPage ledger={ledger} onAction={async () => {}} onRedistribute={async () => undefined} />)

    expect(screen.getByText('当前可分配')).toBeInTheDocument()
    expect(screen.getByText('$5,000.00')).toBeInTheDocument()
    expect(screen.getByText('车轮已实现')).toBeInTheDocument()
    expect(screen.getByText('$2,400.00')).toBeInTheDocument()
    expect(screen.getByText('LEAPS 已实现')).toBeInTheDocument()
    expect(screen.getByText('$5,600.00')).toBeInTheDocument()
    expect(screen.getAllByText('已确认分配')).toHaveLength(2)
    expect(screen.getByText('$3,000.00')).toBeInTheDocument()
    expect(screen.getByText('自动')).toBeInTheDocument()
    expect(screen.getByText('第一批 LEAPS 止盈')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '删除收益流水 wheel-put:1' })).not.toBeInTheDocument()
  })

  it('keeps realized profit entries read-only while retaining internal redistribution', () => {
    render(<ProfitLedgerPage ledger={ledger} onAction={async () => {}} onRedistribute={async () => undefined} />)

    expect(screen.queryByRole('form', { name: '记录已实现盈亏' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '记录流水' })).not.toBeInTheDocument()
    expect(screen.getByRole('form', { name: '生成收益再分配建议' })).toBeInTheDocument()
    expect(screen.getAllByLabelText('只读流水')).toHaveLength(ledger.entries.length)
  })

  it('only records redistribution after explicit confirmation', async () => {
    const user = userEvent.setup()
    const onAction = vi.fn().mockResolvedValue(undefined)
    const onRedistribute = vi.fn().mockResolvedValue({
      allocations: { core: 700, cash: 500, wheel: 0, leaps: 0 },
      unallocated: 0,
    })
    render(<ProfitLedgerPage ledger={ledger} onAction={onAction} onRedistribute={onRedistribute} />)

    const amount = screen.getByLabelText('本次计划分配')
    expect(amount).toHaveValue(5000)
    await user.clear(amount)
    await user.type(amount, '1200')
    await user.click(screen.getByRole('button', { name: '生成缺口建议' }))

    expect(onRedistribute).toHaveBeenCalledWith(1200)
    expect(onAction).not.toHaveBeenCalled()
    expect(screen.getByText('核心仓')).toBeInTheDocument()
    expect(screen.getByText('$700.00')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '确认本次已分配' }))

    expect(onAction).toHaveBeenCalledWith('/profit-ledger/allocations', {
      occurred_on: new Date().toISOString().slice(0, 10),
      amount: 1200,
      allocations: { core: 700, cash: 500, wheel: 0, leaps: 0 },
      note: '按目标缺口确认分配',
    })
  })

  it('does not expose delete or edit controls for imported and historical rows', () => {
    render(<ProfitLedgerPage ledger={ledger} onAction={async () => {}} onRedistribute={async () => undefined} />)

    expect(screen.queryByRole('button', { name: /删除收益流水/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: '删除收益流水' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /修改/ })).not.toBeInTheDocument()
  })
})
