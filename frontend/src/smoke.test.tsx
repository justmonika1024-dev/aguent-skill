import { render, screen } from '@testing-library/react'
import { App } from './app/App'

describe('application smoke test', () => {
  it('renders the product title', async () => {
    render(<App />)
    expect(await screen.findByText('凿 agugent')).toBeInTheDocument()
  })
})
