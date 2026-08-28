import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { Signal } from '../lib/types'
import { SignalsPage } from './SignalsPage'

const signals: Signal[] = [
  {
    id: 10,
    code: 'ma200_break',
    title: '跌破牛熊分界线',
    message: '立即评估平仓止损。',
    severity: 'critical',
    market_date: '2026-08-28',
    acknowledged: false,
  },
  {
    id: 9,
    code: 'core_buy_brk_b',
    title: 'BRK.B 核心仓买入建议',
    message: 'BRK.B 当前为核心仓相对优先缺口，建议金额 14359.71。',
    severity: 'opportunity',
    market_date: '2026-08-27',
    acknowledged: true,
  },
]

describe('signals page', () => {
  it('prioritizes active action and keeps acknowledged core history visible', () => {
    render(<MemoryRouter><SignalsPage signals={signals} onAcknowledge={async () => {}} /></MemoryRouter>)

    const primary = screen.getByRole('region', { name: '当前最优先信号' })
    expect(within(primary).getByText('跌破牛熊分界线')).toBeInTheDocument()
    expect(within(primary).getByRole('button', { name: '标记为已处理' })).toBeInTheDocument()
    const history = screen.getByRole('heading', { name: '近期已确认记录' }).closest('section')!
    expect(within(history).getByText('BRK.B 核心仓买入建议')).toBeInTheDocument()
    expect(within(history).getByText('已确认')).toBeInTheDocument()
    expect(within(history).getByTitle('查看核心仓')).toHaveAttribute('href', '/core')
  })

  it('acknowledges the primary signal from its explicit action button', async () => {
    const user = userEvent.setup()
    const onAcknowledge = vi.fn().mockResolvedValue(undefined)
    render(<MemoryRouter><SignalsPage signals={signals} onAcknowledge={onAcknowledge} /></MemoryRouter>)

    await user.click(screen.getByRole('button', { name: '标记为已处理' }))

    expect(onAcknowledge).toHaveBeenCalledWith(10)
  })

  it('explains that handled signals remain in history when the queue is clear', () => {
    render(<MemoryRouter><SignalsPage signals={[signals[1]]} onAcknowledge={async () => {}} /></MemoryRouter>)

    expect(screen.getByRole('region', { name: '无待处理信号' })).toHaveTextContent('已确认建议仍保留在下方近期记录')
    expect(screen.getByText('BRK.B 核心仓买入建议')).toBeInTheDocument()
  })
})
