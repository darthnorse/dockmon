import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BatchJobPanel } from './BatchJobPanel'
import { WebSocketContext } from '@/lib/websocket/WebSocketProvider'
import type { WebSocketMessage } from '@/lib/websocket/useWebSocket'

const getMock = vi.hoisted(() => vi.fn())

vi.mock('@/lib/api/client', () => ({ apiClient: { get: getMock } }))
vi.mock('@/features/auth/AuthContext', () => ({
  useAuth: () => ({ hasCapability: () => true }),
}))
vi.mock('@/lib/hooks/useUserPreferences', () => ({
  useTimeFormat: () => ({ timeFormat: '24h' }),
}))

function makeJob(overrides: Record<string, unknown> = {}) {
  return {
    id: 'job_1',
    scope: 'container',
    action: 'update-containers',
    status: 'running',
    total_items: 2,
    completed_items: 2,
    success_items: 1,
    error_items: 1,
    skipped_items: 0,
    created_at: '2026-11-06T17:42:09Z',
    items: [
      { id: 1, container_id: 'aaa111111111', container_name: 'qbittorrent', host_id: 'h1', status: 'success', message: 'Update completed successfully' },
      { id: 2, container_id: 'bbb222222222', container_name: 'gluetun', host_id: 'h1', status: 'error', message: 'Container update failed' },
    ],
    ...overrides,
  }
}

async function renderPanel(onJobComplete = vi.fn()) {
  let handler: ((message: WebSocketMessage) => void) | null = null
  const addMessageHandler = (h: (message: WebSocketMessage) => void) => {
    handler = h
    return () => { handler = null }
  }
  const queryClient = new QueryClient()
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

  const view = render(
    <QueryClientProvider client={queryClient}>
      <WebSocketContext.Provider value={{ status: 'connected', send: vi.fn(), addMessageHandler }}>
        <BatchJobPanel jobId="job_1" isVisible onClose={vi.fn()} onJobComplete={onJobComplete} />
      </WebSocketContext.Provider>
    </QueryClientProvider>
  )
  await waitFor(() => expect(screen.getByText('gluetun')).toBeInTheDocument())

  return {
    container: view.container,
    invalidate,
    send: (message: WebSocketMessage) => act(() => handler?.(message)),
  }
}

describe('BatchJobPanel', () => {
  beforeEach(() => {
    getMock.mockReset()
    getMock.mockResolvedValue(makeJob())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('treats a partial job as finished', async () => {
    const onJobComplete = vi.fn()
    const { send, invalidate } = await renderPanel(onJobComplete)
    vi.useFakeTimers()

    send({ type: 'batch_job_update', data: { job_id: 'job_1', status: 'partial' } })

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['containers'] })
    act(() => { vi.advanceTimersByTime(3000) })
    expect(onJobComplete).toHaveBeenCalledOnce()
  })

  it('shows the completion footer for a partial job', async () => {
    getMock.mockResolvedValue(makeJob({ status: 'partial', completed_at: '2026-11-06T17:47:09Z' }))

    await renderPanel()

    expect(screen.getByText(/Completed at/)).toBeInTheDocument()
  })

  it('shows the backend item statuses with an icon, and errors in red', async () => {
    const { container } = await renderPanel()

    expect(container.querySelector('svg.text-success')).toBeInTheDocument()
    expect(container.querySelector('svg.text-destructive')).toBeInTheDocument()
    expect(screen.getByText('Container update failed')).toHaveClass('text-destructive')
  })
})
