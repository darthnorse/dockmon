import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StatsTimeRangeSelector } from './StatsTimeRangeSelector'

describe('StatsTimeRangeSelector', () => {
  it('renders all 6 buttons with correct labels', () => {
    render(<StatsTimeRangeSelector value="live" onChange={() => {}} />)
    const labels = ['Live', '1h', '8h', '24h', '7d', '30d']
    for (const label of labels) {
      expect(screen.getByRole('button', { name: new RegExp(`^${label}$`) })).toBeInTheDocument()
    }
  })

  it('marks the current value button as active', () => {
    render(<StatsTimeRangeSelector value="24h" onChange={() => {}} />)
    const active = screen.getByRole('button', { name: /^24h$/ })
    expect(active).toHaveAttribute('aria-pressed', 'true')
  })

  it('calls onChange with the clicked range', async () => {
    const onChange = vi.fn()
    render(<StatsTimeRangeSelector value="live" onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: /^7d$/ }))
    expect(onChange).toHaveBeenCalledWith('7d')
  })

  it('renders a live-indicator dot only when live is the active value', () => {
    const { rerender } = render(<StatsTimeRangeSelector value="live" onChange={() => {}} />)
    expect(screen.getByTestId('live-indicator')).toBeInTheDocument()

    rerender(<StatsTimeRangeSelector value="1h" onChange={() => {}} />)
    expect(screen.queryByTestId('live-indicator')).not.toBeInTheDocument()
  })
})
