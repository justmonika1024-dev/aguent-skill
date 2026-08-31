import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AppShell } from './AppShell'

describe('AppShell', () => {
  it('shows every MVP navigation destination', async () => {
    render(<MemoryRouter><AppShell /></MemoryRouter>)
    for (const label of ['工作台', '运行历史', '正式梗库', '策略版本', '设置']) {
      expect(await screen.findByText(label)).toBeInTheDocument()
    }
  })
})
