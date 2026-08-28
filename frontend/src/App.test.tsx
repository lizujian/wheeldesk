import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { AppShell } from './components/AppShell'

describe('App', () => {
  beforeEach(() => { vi.spyOn(window, 'scrollTo').mockImplementation(() => {}) })

  it('renders the operating-console destinations including rebalancing', () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )

    const navigation = screen.getByRole('navigation', { name: '主导航' })
    for (const label of ['总览', '核心仓', '车轮', 'LEAPS', '再平衡', '收益', '账本', '其他', '导入', '信号', '设置']) {
      expect(within(navigation).getByRole('link', { name: label })).toBeInTheDocument()
    }
    expect(within(navigation).queryByRole('link', { name: '待退出仓' })).not.toBeInTheDocument()
  })

  it('returns the document to the top after sidebar navigation', async () => {
    const user = userEvent.setup()
    const scrollTo = vi.mocked(window.scrollTo)
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )
    scrollTo.mockClear()

    const navigation = screen.getByRole('navigation', { name: '主导航' })
    await user.click(within(navigation).getByRole('link', { name: '核心仓' }))

    expect(scrollTo).toHaveBeenCalledWith(0, 0)
  })

  it('shows a global critical signal indicator in navigation and the top bar', () => {
    render(
      <MemoryRouter>
        <AppShell market={null} refreshing={false} onRefresh={() => {}} signalCount={3} criticalSignalCount={1}>
          <div>content</div>
        </AppShell>
      </MemoryRouter>,
    )

    const navigation = screen.getByRole('navigation', { name: '主导航' })
    expect(within(navigation).getByRole('link', { name: /信号\s*3/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '3 条待处理信号' })).toHaveClass('critical')
    expect(screen.getByText('1 条高危')).toBeInTheDocument()
  })
})
