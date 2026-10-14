import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../lib/api'
import type { MarketSettings } from '../lib/types'
import { SettingsPage } from './SettingsPage'

const defaultSettings: MarketSettings = { provider: 'ibkr', ibkr_host: null, ibkr_port: null, ibkr_client_id: 71, configured: false, effective_provider: 'ibkr', vix_provider: 'ibkr', config_key: 'ibkr', club_symbols: ['AAPL', 'AVGO'] }

describe('market settings', () => {
  beforeEach(() => { vi.restoreAllMocks(); vi.spyOn(api, 'marketSettings').mockResolvedValue(defaultSettings) })

  it('uses only IB Gateway and makes login ownership explicit', async () => {
    render(<MemoryRouter><SettingsPage portfolio={{ initialized: false }} market={null} onReset={async () => {}} /></MemoryRouter>)
    expect(await screen.findByRole('button', { name: '保存行情设置' })).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.getByText(/盈透账号在 IB Gateway 或 TWS 中登录/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/密码/)).not.toBeInTheDocument()
  })

  it('saves the endpoint and user-managed club members with VIX on IBKR', async () => {
    const user = userEvent.setup()
    const saved: MarketSettings = { ...defaultSettings, provider: 'ibkr', effective_provider: 'ibkr', ibkr_host: 'localhost', ibkr_port: 4002, configured: true, config_key: 'ibkr' }
    const save = vi.spyOn(api, 'saveMarketSettings').mockResolvedValue(saved)
    const onSaved = vi.fn()
    render(<MemoryRouter><SettingsPage portfolio={{ initialized: false }} market={null} onReset={async () => {}} onMarketSettingsSaved={onSaved} /></MemoryRouter>)
    await screen.findByRole('button', { name: '保存行情设置' })
    await user.clear(screen.getByLabelText('万亿俱乐部股票列表')); await user.type(screen.getByLabelText('万亿俱乐部股票列表'), 'AAPL, AVGO')
    await user.clear(screen.getByLabelText('IB Gateway 地址')); await user.type(screen.getByLabelText('IB Gateway 地址'), 'localhost')
    await user.clear(screen.getByLabelText('IB Gateway 端口')); await user.type(screen.getByLabelText('IB Gateway 端口'), '4002')
    await user.click(screen.getByRole('button', { name: '保存行情设置' }))
    expect(save).toHaveBeenCalledWith({ provider: 'ibkr', ibkr_host: 'localhost', ibkr_port: 4002, ibkr_client_id: 71, club_symbols: ['AAPL', 'AVGO'] })
    expect(onSaved).toHaveBeenCalledWith(saved)
    expect(await screen.findByText('已保存。股票、期权和 VIX 均使用 IB Gateway，请手动刷新行情。')).toBeInTheDocument()
  })

  it('tests an unsaved connection and reports an offline IB Gateway without changing the source', async () => {
    const user = userEvent.setup()
    const save = vi.spyOn(api, 'saveMarketSettings')
    vi.spyOn(api, 'testIbkrConnection').mockResolvedValue({ connected: false, error: '无法连接 IB Gateway，请先启动服务' })
    render(<MemoryRouter><SettingsPage portfolio={{ initialized: false }} market={null} onReset={async () => {}} /></MemoryRouter>)
    await screen.findByRole('button', { name: '测试 IB Gateway 连接' })
    await user.click(screen.getByRole('button', { name: '测试 IB Gateway 连接' }))
    expect(await screen.findByText('无法连接 IB Gateway，请先启动服务')).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
  })
})


it('shows the actual VIX and stock quote quality from Gateway diagnostics', async () => {
  vi.spyOn(api, 'marketSettings').mockResolvedValue(defaultSettings)
  vi.spyOn(api, 'testIbkrConnection').mockResolvedValue({ connected: true, client_readonly: true, positions_count: 22, qqq: { price: 743.78, source: 'ibkr', quality: 'delayed', market_as_of: null, fetched_at: '2026-10-14T10:00:00Z' }, vix: { price: 15.19, source: 'ibkr', quality: 'delayed', market_as_of: null, fetched_at: '2026-10-14T10:00:00Z' } })
  const user = userEvent.setup()
  render(<MemoryRouter><SettingsPage portfolio={{ initialized: false }} market={null} onReset={async () => {}} /></MemoryRouter>)
  await user.click(await screen.findByRole('button', { name: '测试 IB Gateway 连接' }))
  expect(await screen.findByText('VIX 15.19 · IBKR · 延迟行情')).toBeInTheDocument()
  expect(screen.getByText('QQQ 743.78 · IBKR · 延迟行情')).toBeInTheDocument()
})
