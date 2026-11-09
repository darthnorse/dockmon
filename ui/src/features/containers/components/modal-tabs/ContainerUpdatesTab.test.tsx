import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@/test/utils'
import { ContainerUpdatesTab } from './ContainerUpdatesTab'
import * as apiClient from '@/lib/api/client'
import type { Container, ContainerUpdateStatus } from '../../types'

vi.mock('@/lib/api/client', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}))

const container = {
  id: 'abc123def456',
  name: 'app',
  image: 'nginx:1.25.3',
  state: 'running',
  status: 'Up',
  created: '2026-11-08T00:00:00Z',
  ports: [],
  labels: {},
  host_id: 'host-1',
  host_name: 'host1',
} as unknown as Container

function mockStatus(status: ContainerUpdateStatus['status'], autoUpdateEnabled = true) {
  vi.mocked(apiClient.apiClient.get).mockImplementation((url: string) => {
    if (url.endsWith('/update-status')) {
      return Promise.resolve({
        status,
        update_available: true,
        current_image: 'nginx:1.25.3',
        current_digest: 'aaaaaaaaaaaa',
        latest_image: 'nginx:1',
        latest_digest: 'bbbbbbbbbbbb',
        floating_tag_mode: 'minor',
        last_checked_at: '2026-11-08T00:00:00Z',
        auto_update_enabled: autoUpdateEnabled,
      })
    }
    return Promise.resolve({})
  })
}

const CALLOUT = /can't confirm the running image came from the registry, so auto-update won't apply this update/

describe('ContainerUpdatesTab unverified image', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it.each([true, false])('explains why auto-update is paused (auto-update %s)', async (autoUpdateEnabled) => {
    mockStatus('unverified_image', autoUpdateEnabled)

    render(<ContainerUpdatesTab container={container} />)

    expect(await screen.findByText(CALLOUT)).toBeInTheDocument()
    expect(screen.getByText(/switch to exact tracking/)).toBeInTheDocument()
    expect(screen.getByText(/Paused for this update/)).toBeInTheDocument()
  })

  it('shows no callout for a confirmed update', async () => {
    mockStatus(null)

    render(<ContainerUpdatesTab container={container} />)

    expect(await screen.findByText('Update Available')).toBeInTheDocument()
    expect(screen.queryByText(CALLOUT)).not.toBeInTheDocument()
    expect(screen.queryByText(/Paused for this update/)).not.toBeInTheDocument()
  })
})
