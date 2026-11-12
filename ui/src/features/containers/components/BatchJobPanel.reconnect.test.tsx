import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { apiClient, ApiError } from '@/lib/api/client'
import type { WebSocketMessage } from '@/lib/websocket/useWebSocket'
import { BatchJobPanel } from './BatchJobPanel'

vi.mock('@/lib/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/client')>()
  return { ...actual, apiClient: { get: vi.fn() } }
})

let wsStatus = 'connected'
let wsHandler: ((message: WebSocketMessage) => void) | null = null
vi.mock('@/lib/websocket/WebSocketProvider', () => ({
  useWebSocketContext: () => ({
    status: wsStatus,
    send: vi.fn(),
    addMessageHandler: (handler: (message: WebSocketMessage) => void) => {
      wsHandler = handler
      return () => {
        wsHandler = null
      }
    },
  }),
}))

vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ hasCapability: () => true }),
}))

vi.mock('@/lib/hooks/useUserPreferences', () => ({
  useTimeFormat: () => ({ timeFormat: '24h' }),
}))

const JOB_ID = 'job_abc'

function makeJob(status: 'running' | 'completed', itemStatus: 'running' | 'success' = 'running') {
  return {
    id: JOB_ID,
    scope: 'container',
    action: 'update-containers',
    status,
    total_items: 1,
    completed_items: status === 'completed' ? 1 : 0,
    success_items: status === 'completed' ? 1 : 0,
    error_items: 0,
    skipped_items: 0,
    created_at: '2026-11-12T18:54:23Z',
    items: [
      { id: 1, container_id: 'abc123def456', container_name: 'caddy', host_id: 'h1', host_name: 'proxy-host', status: itemStatus },
    ],
  }
}

const networkError = () => new TypeError('Failed to fetch')

describe('BatchJobPanel', () => {
  let onJobComplete: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(apiClient.get).mockReset()
    wsStatus = 'connected'
    wsHandler = null
    onJobComplete = vi.fn()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function renderPanel() {
    const queryClient = new QueryClient()
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const props = { jobId: JOB_ID, isVisible: true, onClose: vi.fn(), onJobComplete }
    const view = render(<BatchJobPanel {...props} />, { wrapper })
    return { ...view, rerenderPanel: () => view.rerender(<BatchJobPanel {...props} />) }
  }

  const flush = async (ms = 0) => {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms)
    })
  }

  it('retries a connection failure quietly and shows the job once reachable', async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(networkError())
      .mockRejectedValueOnce(networkError())
      .mockResolvedValueOnce(makeJob('running'))
    renderPanel()
    await flush()

    expect(screen.queryByText('Failed to load batch job')).not.toBeInTheDocument()
    expect(screen.getByText(/Reconnecting/)).toBeInTheDocument()

    await flush(1000)
    await flush(2000)

    expect(apiClient.get).toHaveBeenCalledTimes(3)
    expect(screen.getByText('caddy', { selector: 'div' })).toBeInTheDocument()
    expect(screen.queryByText(/Reconnecting/)).not.toBeInTheDocument()
    expect(screen.queryByText('Failed to load batch job')).not.toBeInTheDocument()
  })

  it('gives up after the retries and offers a manual retry', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(networkError())
    renderPanel()
    await flush()
    await flush(1000)
    await flush(2000)
    await flush(4000)

    expect(apiClient.get).toHaveBeenCalledTimes(4)
    expect(screen.getByText('Failed to load batch job')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('shows an HTTP error immediately without retrying', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError('Batch job not found', 404))
    renderPanel()
    await flush()
    await flush(8000)

    expect(apiClient.get).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Failed to load batch job')).toBeInTheDocument()
    expect(screen.getByText('Batch job not found')).toBeInTheDocument()
  })

  it('loads the job when a live update arrives after the first load failed', async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError('Internal server error', 500))
    renderPanel()
    await flush()
    expect(screen.getByText('Failed to load batch job')).toBeInTheDocument()

    vi.mocked(apiClient.get).mockResolvedValue(makeJob('completed', 'success'))
    await act(async () => {
      wsHandler?.({ type: 'batch_job_update', data: { job_id: JOB_ID, status: 'completed' } } as WebSocketMessage)
    })
    await flush()

    expect(screen.queryByText('Failed to load batch job')).not.toBeInTheDocument()
    expect(screen.getByText(/1 success/)).toBeInTheDocument()
  })

  it('clears a shown error when a live update for the job arrives', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce(makeJob('running'))
    const { rerenderPanel } = renderPanel()
    await flush()

    vi.mocked(apiClient.get).mockRejectedValueOnce(new ApiError('Internal server error', 500))
    wsStatus = 'disconnected'
    rerenderPanel()
    await flush()
    wsStatus = 'connected'
    rerenderPanel()
    await flush()
    expect(screen.getByText('Failed to load batch job')).toBeInTheDocument()

    await act(async () => {
      wsHandler?.({ type: 'batch_item_update', data: { job_id: JOB_ID, item_id: 1, status: 'success' } } as WebSocketMessage)
    })

    expect(screen.queryByText('Failed to load batch job')).not.toBeInTheDocument()
  })

  it('re-fetches a running job when the live connection comes back, and finishes it', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce(makeJob('running'))
    const { rerenderPanel } = renderPanel()
    await flush()
    expect(apiClient.get).toHaveBeenCalledTimes(1)

    wsStatus = 'disconnected'
    rerenderPanel()
    await flush()
    vi.mocked(apiClient.get).mockResolvedValueOnce(makeJob('completed', 'success'))
    wsStatus = 'connected'
    rerenderPanel()
    await flush()

    expect(apiClient.get).toHaveBeenCalledTimes(2)
    expect(screen.getByText(/1 success/)).toBeInTheDocument()
    await flush(3000)
    expect(onJobComplete).toHaveBeenCalledTimes(1)
  })

  it('does not re-fetch on reconnect once the job has finished', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce(makeJob('completed', 'success'))
    const { rerenderPanel } = renderPanel()
    await flush()

    wsStatus = 'disconnected'
    rerenderPanel()
    await flush()
    wsStatus = 'connected'
    rerenderPanel()
    await flush()

    expect(apiClient.get).toHaveBeenCalledTimes(1)
  })

  it('retries a gateway error while DockMon restarts behind a proxy', async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new ApiError('Bad gateway', 502))
      .mockRejectedValueOnce(new ApiError('Service unavailable', 503))
      .mockResolvedValueOnce(makeJob('running'))
    renderPanel()
    await flush()
    expect(screen.queryByText('Failed to load batch job')).not.toBeInTheDocument()

    await flush(1000)
    await flush(2000)

    expect(apiClient.get).toHaveBeenCalledTimes(3)
    expect(screen.getByText('caddy', { selector: 'div' })).toBeInTheDocument()
  })

  it('does not restart the load for every live message while the first fetch is pending', async () => {
    let resolveFirst: (job: unknown) => void = () => {}
    vi.mocked(apiClient.get)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValue(makeJob('running', 'success'))
    renderPanel()
    await flush()

    await act(async () => {
      for (let i = 0; i < 5; i++) {
        wsHandler?.({ type: 'batch_item_update', data: { job_id: JOB_ID, item_id: 1, status: 'running' } } as WebSocketMessage)
      }
    })
    expect(apiClient.get).toHaveBeenCalledTimes(1)

    await act(async () => resolveFirst(makeJob('running')))
    await flush()

    expect(apiClient.get).toHaveBeenCalledTimes(2)
    expect(screen.getByText('caddy', { selector: 'div' })).toBeInTheDocument()
  })

  it('keeps live updates when an older snapshot lands after them', async () => {
    let resolveRefresh: (job: unknown) => void = () => {}
    vi.mocked(apiClient.get).mockResolvedValueOnce(makeJob('running'))
    const { rerenderPanel } = renderPanel()
    await flush()

    vi.mocked(apiClient.get).mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve }))
    wsStatus = 'disconnected'
    rerenderPanel()
    await flush()
    wsStatus = 'connected'
    rerenderPanel()
    await flush()

    await act(async () => {
      wsHandler?.({
        type: 'batch_job_update',
        data: { job_id: JOB_ID, status: 'completed', completed_items: 1, success_items: 1 },
      } as WebSocketMessage)
    })
    await act(async () => resolveRefresh(makeJob('running')))
    await flush()

    expect(screen.getByText(/1 success/)).toBeInTheDocument()
    expect(screen.getByText('1 of 1')).toBeInTheDocument()
  })

  it('drops the previous job when a new batch starts', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce(makeJob('running'))
    const queryClient = new QueryClient()
    const props = { isVisible: true, onClose: vi.fn(), onJobComplete }
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <BatchJobPanel jobId={JOB_ID} {...props} />
      </QueryClientProvider>,
    )
    await flush()

    let resolveNext: (job: unknown) => void = () => {}
    vi.mocked(apiClient.get).mockImplementationOnce(() => new Promise((resolve) => { resolveNext = resolve }))
    rerender(
      <QueryClientProvider client={queryClient}>
        <BatchJobPanel jobId="job_next" {...props} />
      </QueryClientProvider>,
    )
    await flush()

    expect(screen.queryByText('caddy', { selector: 'div' })).not.toBeInTheDocument()
    await act(async () => {
      wsHandler?.({ type: 'batch_job_update', data: { job_id: 'job_next', status: 'completed' } } as WebSocketMessage)
    })
    await flush(3000)
    expect(onJobComplete).not.toHaveBeenCalled()
    resolveNext({ ...makeJob('running'), id: 'job_next' })
    await flush()
  })
})
