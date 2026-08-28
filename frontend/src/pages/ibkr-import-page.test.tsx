import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../lib/api'
import type { IbkrAutoImportResult } from '../lib/types'
import { IbkrImportPage } from './IbkrImportPage'

vi.mock('../lib/api', () => ({
  api: {
    ibkrAutoImport: vi.fn(),
    ibkrHistory: vi.fn(),
  },
}))

const result: IbkrAutoImportResult = {
  filename: 'activity.csv',
  report_as_of: '2026-08-27',
  statement_rows: 14,
  imported: 2,
  unchanged: 4,
  needs_attention: 0,
  results: [
    {
      fingerprint: 'put-row',
      instrument: 'TQQQ 2026-10-02 $55 Put',
      action: 'create_wheel_put',
      entity_type: 'wheel_put',
      entity_id: 7,
    },
    {
      fingerprint: 'roll-row',
      instrument: 'MSFT Long Call 展期',
      action: 'roll_position',
      entity_type: 'position',
      entity_id: 9,
    },
  ],
  notices: [],
}

describe('IBKR import page', () => {
  beforeEach(() => {
    vi.mocked(api.ibkrHistory).mockResolvedValue([])
    vi.mocked(api.ibkrAutoImport).mockResolvedValue(result)
  })

  it('imports a selected CSV immediately without preview or confirmation', async () => {
    const user = userEvent.setup()
    const onImported = vi.fn().mockResolvedValue(undefined)
    render(<IbkrImportPage onImported={onImported} />)

    const file = new File(['statement'], 'activity.csv', { type: 'text/csv' })
    Object.defineProperty(file, 'text', { value: vi.fn().mockResolvedValue('statement') })
    await user.upload(screen.getByLabelText('选择 IBKR CSV'), file)

    expect(await screen.findByText('本次写入')).toBeInTheDocument()
    expect(screen.getByText('TQQQ 2026-10-02 $55 Put')).toBeInTheDocument()
    expect(screen.getByText('MSFT Long Call 展期')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /确认导入/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(api.ibkrAutoImport).toHaveBeenCalledWith({
      filename: 'activity.csv',
      content: 'statement',
    })
    expect(onImported).toHaveBeenCalled()
  })

  it('shows read-only import history without a source column', async () => {
    const user = userEvent.setup()
    vi.mocked(api.ibkrHistory).mockResolvedValue([{
      id: 1, filename: 'activity.csv', section: 'Open Positions', row_index: 2,
      action: 'create_position', entity_type: 'position', entity_id: 7,
      instrument: 'QQQ', created_at: '2026-08-26T12:00:00',
    }])
    render(<IbkrImportPage onImported={async () => {}} />)

    await user.click(screen.getByRole('button', { name: '导入记录' }))
    expect(await screen.findByText('最近导入记录')).toBeInTheDocument()
    expect(screen.getByText('activity.csv')).toBeInTheDocument()
    expect(screen.getByText('position 7')).toBeInTheDocument()
    expect(screen.queryByText('来源')).not.toBeInTheDocument()
  })
})
