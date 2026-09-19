import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { StatsSection } from './StatsSection'
import { STORAGE_KEY } from './useLastSelectedRange'
import { apiClient } from '@/lib/api/client'
import type { StatsHistoryResponse } from './historyTypes'

vi.mock('@/lib/api/client', () => ({
  apiClient: { get: vi.fn() },
}))
const mockGet = apiClient.get as unknown as ReturnType<typeof vi.fn>

// Mock StatsCharts: it uses uPlot which needs real DOM APIs (ResizeObserver,
// canvas context) that jsdom does not provide. We assert on props directly.
vi.mock('@/lib/charts/StatsCharts', () => ({
  StatsCharts: (props: { footer?: string; cpuValue?: string }) => (
    <div data-testid="stats-charts">
      {props.cpuValue && <span data-testid="cpu-value">{props.cpuValue}</span>}
      {props.footer && <p>{props.footer}</p>}
    </div>
  ),
}))

// Mock useLiveHistory so these tests stay focused on range routing + historical
// loading. The live one-time fetch + append logic is covered by
// useLiveHistory.test.ts. Returning no data makes the Live range fall back to
// the broadcast liveData (and avoids a live-endpoint call here).
vi.mock('./useLiveHistory', () => ({
  useLiveHistory: () => ({
    data: undefined,
    isLoading: false,
    isError: false,
    windowSeconds: 600,
  }),
}))

function makeLiveData() {
  return {
    cpu: [1, 2, 3],
    mem: [10, 11, 12],
    net: [100, 200, 300],
    timestamps: [0, 7, 14],
    cpuValue: '3%',
    memValue: '12%',
    netValue: '300 B/s',
  }
}

function makeHistoryResponse(): StatsHistoryResponse {
  return {
    tier: '1h',
    tier_seconds: 3600,
    interval_seconds: 7,
    from: 0,
    to: 14,
    server_time: 14,
    timestamps: [0, 7, 14],
    cpu: [5, null, 7],
    mem: [50, 55, null],
    net_bps: [500, 600, 700],
  }
}

describe('StatsSection', () => {
  beforeEach(() => {
    localStorage.clear()
    mockGet.mockReset()
  })

  it('renders Live charts when range is live (default)', () => {
    render(<StatsSection hostId="h1" liveData={makeLiveData()} />)
    expect(screen.getByRole('button', { name: /^Live$/ })).toHaveAttribute(
      'aria-pressed', 'true')
    expect(mockGet).not.toHaveBeenCalled()
  })

  it('switches to historical mode and calls the history endpoint', async () => {
    mockGet.mockResolvedValueOnce(makeHistoryResponse())
    render(<StatsSection hostId="h1" liveData={makeLiveData()} />)

    await userEvent.click(screen.getByRole('button', { name: /^1h$/ }))

    await screen.findByText(/data points/)
    expect(mockGet).toHaveBeenCalledWith(
      '/hosts/h1/stats/history',
      { params: { range: '1h' } },
    )
  })

  it('persists selected range across re-mount via localStorage', async () => {
    localStorage.setItem(STORAGE_KEY, '24h')
    mockGet.mockResolvedValue(makeHistoryResponse())
    render(<StatsSection hostId="h1" liveData={makeLiveData()} />)
    // Opens on 24h without user interaction
    expect(screen.getByRole('button', { name: /^24h$/ })).toHaveAttribute(
      'aria-pressed', 'true')
  })

  it('shows inline error with Retry button when historical fetch fails', async () => {
    mockGet.mockRejectedValueOnce(new Error('fail'))
    render(<StatsSection hostId="h1" liveData={makeLiveData()} />)
    await userEvent.click(screen.getByRole('button', { name: /^1h$/ }))
    await screen.findByText(/Failed to load history/)
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument()
  })

  it('shows footer with data points and resolution on historical success', async () => {
    mockGet.mockResolvedValueOnce(makeHistoryResponse())
    render(<StatsSection hostId="h1" liveData={makeLiveData()} />)
    await userEvent.click(screen.getByRole('button', { name: /^1h$/ }))
    // 2 non-null CPU values in the mock, out of 3 slots -> we show the
    // non-null count and the interval_seconds from the response.
    await screen.findByText(/2 data points \(7s resolution\)/)
  })
})
