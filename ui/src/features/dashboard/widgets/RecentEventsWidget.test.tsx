/**
 * RecentEventsWidget Tests
 * Tests event list rendering, icons, and timestamps
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import { RecentEventsWidget } from './RecentEventsWidget'
import * as apiClient from '@/lib/api/client'

vi.mock('@/lib/api/client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

vi.mock('@/lib/hooks/useUserPreferences', () => ({
  useTimeFormat: () => ({ timeFormat: '24h', setTimeFormat: vi.fn() }),
}))

const renderWidget = () => render(<RecentEventsWidget />)

interface TestEventInput {
  id: number
  title: string
  category?: string
  container_name?: string | null
  timestamp: string
}

const makeEvent = (overrides: Partial<TestEventInput> & Pick<TestEventInput, 'id' | 'title' | 'timestamp'>) => ({
  event_type: 'container_started',
  category: 'container',
  severity: 'info',
  ...overrides,
})

describe('RecentEventsWidget', () => {
  describe('loading state', () => {
    it('should show loading skeleton', () => {
      vi.mocked(apiClient.apiClient.get).mockImplementation(
        () => new Promise(() => {})
      )

      renderWidget()

      expect(screen.getByText('Recent Events')).toBeInTheDocument()
      const skeletons = document.querySelectorAll('.animate-pulse')
      expect(skeletons.length).toBeGreaterThan(0)
    })
  })

  describe('error state', () => {
    it('should show error message when API fails', async () => {
      vi.mocked(apiClient.apiClient.get).mockRejectedValue(
        new Error('Network error')
      )

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Failed to load events')).toBeInTheDocument()
      })
    })
  })

  describe('data rendering', () => {
    it('should display empty state when no events', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({ events: [] })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('No recent events')).toBeInTheDocument()
      })
    })

    it('should display container name when present', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: [
          makeEvent({
            id: 1,
            title: 'Container started',
            container_name: 'nginx',
            timestamp: '2025-01-07T10:00:00Z',
          }),
          makeEvent({
            id: 2,
            title: 'Container stopped',
            container_name: 'postgres',
            timestamp: '2025-01-07T09:50:00Z',
          }),
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
        expect(screen.getByText('postgres')).toBeInTheDocument()
      })
    })

    it('should fall back to title when container name missing', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: [
          makeEvent({
            id: 1,
            title: 'Host went offline',
            category: 'host',
            container_name: null,
            timestamp: '2025-01-07T10:00:00Z',
          }),
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Host went offline')).toBeInTheDocument()
      })
    })

    it('should render multiple events', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: Array.from({ length: 5 }, (_, i) =>
          makeEvent({
            id: i + 1,
            title: 'Container started',
            container_name: `container-${i}`,
            timestamp: new Date().toISOString(),
          })
        ),
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('container-0')).toBeInTheDocument()
        expect(screen.getByText('container-4')).toBeInTheDocument()
      })
    })
  })

  describe('layout', () => {
    it('should have scrollable content area', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: Array.from({ length: 10 }, (_, i) =>
          makeEvent({
            id: i + 1,
            title: 'Container started',
            container_name: `container-${i}`,
            timestamp: new Date().toISOString(),
          })
        ),
      })

      renderWidget()

      await waitFor(() => {
        const card = screen.getByText('Recent Events').closest('.flex.flex-col')
        expect(card).toBeInTheDocument()
      })
    })
  })
})
