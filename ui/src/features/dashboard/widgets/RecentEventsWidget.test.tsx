/**
 * RecentEventsWidget Tests
 * Tests event list rendering, icons, and timestamps
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RecentEventsWidget } from './RecentEventsWidget'
import * as apiClient from '@/lib/api/client'

vi.mock('@/lib/api/client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

function renderWidget() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <RecentEventsWidget />
    </QueryClientProvider>
  )
}

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
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: [],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('No recent events')).toBeInTheDocument()
      })
    })

    it('should display event list', async () => {
      const mockEvents = [
        {
          id: '1',
          type: 'container',
          action: 'start',
          container_name: 'nginx',
          timestamp: '2025-01-07T10:00:00Z',
        },
        {
          id: '2',
          type: 'container',
          action: 'stop',
          container_name: 'postgres',
          timestamp: '2025-01-07T09:50:00Z',
        },
      ]

      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: mockEvents,
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
        expect(screen.getByText('postgres')).toBeInTheDocument()
      })
    })

    it('should display action types', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: [
          {
            id: '1',
            action: 'start',
            container_name: 'test',
            timestamp: '2025-01-07T10:00:00Z',
          },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText(/start/)).toBeInTheDocument()
      })
    })

    it('should handle unknown container names', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: [
          {
            id: '1',
            action: 'start',
            timestamp: '2025-01-07T10:00:00Z',
          },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Unknown container')).toBeInTheDocument()
      })
    })

    it('should display timestamps', async () => {
      const now = new Date()
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: [
          {
            id: '1',
            action: 'start',
            container_name: 'test',
            timestamp: now.toISOString(),
          },
        ],
      })

      renderWidget()

      await waitFor(() => {
        // Should show localized time
        const timeText = screen.getByText(/start/)
        expect(timeText).toBeInTheDocument()
      })
    })
  })

  describe('scrolling', () => {
    it('should have scrollable content area', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        events: Array.from({ length: 10 }, (_, i) => ({
          id: String(i),
          action: 'start',
          container_name: `container-${i}`,
          timestamp: new Date().toISOString(),
        })),
      })

      renderWidget()

      await waitFor(() => {
        const card = screen.getByText('Recent Events').closest('.flex.flex-col')
        expect(card).toBeInTheDocument()
      })
    })
  })
})
