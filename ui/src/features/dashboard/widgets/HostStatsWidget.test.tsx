/**
 * HostStatsWidget Tests
 * Tests loading, error, and data rendering states
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HostStatsWidget } from './HostStatsWidget'
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
      <HostStatsWidget />
    </QueryClientProvider>
  )
}

describe('HostStatsWidget', () => {
  describe('loading state', () => {
    it('should show loading skeleton', () => {
      vi.mocked(apiClient.apiClient.get).mockImplementation(
        () => new Promise(() => {})
      )

      renderWidget()

      expect(screen.getByText('Hosts')).toBeInTheDocument()
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
        expect(screen.getByText('Failed to load host stats')).toBeInTheDocument()
      })
    })
  })

  describe('data rendering', () => {
    it('should display total host count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([
        { id: '1', name: 'host1', status: 'online' },
        { id: '2', name: 'host2', status: 'online' },
        { id: '3', name: 'host3', status: 'offline' },
      ])

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Registered hosts')).toBeInTheDocument()
        // Get the total count element (the large number above "Registered hosts")
        const totalElement = screen.getByText('Registered hosts').previousElementSibling
        expect(totalElement?.textContent).toBe('3')
      })
    })

    it('should display online status', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([
        { id: '1', status: 'online' },
        { id: '2', status: 'online' },
      ])

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Online')).toBeInTheDocument()
        // Check that online count shows 2 - use parent's parent to get the full row
        const onlineText = screen.getByText('Online')
        const onlineRow = onlineText.parentElement?.parentElement
        expect(onlineRow?.textContent).toContain('Online2')
      })
    })

    it('should not display offline status (not yet implemented)', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([
        { id: '1', status: 'online' },
        { id: '2', status: 'offline' },
      ])

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Online')).toBeInTheDocument()
        // Widget currently treats all registered hosts as online
        // Offline detection requires ping/healthcheck (future enhancement)
        expect(screen.queryByText('Offline')).not.toBeInTheDocument()

        // Total count should still be 2
        const totalElement = screen.getByText('Registered hosts').previousElementSibling
        expect(totalElement?.textContent).toBe('2')
      })
    })

    it('should handle empty host list', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([])

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Registered hosts')).toBeInTheDocument()
        // Should have "0" as the total count
        const totalElement = screen.getByText('Registered hosts').previousElementSibling
        expect(totalElement?.textContent).toBe('0')
      })
    })
  })
})
