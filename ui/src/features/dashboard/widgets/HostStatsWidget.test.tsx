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
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        hosts: [
          { id: '1', name: 'host1', status: 'online' },
          { id: '2', name: 'host2', status: 'online' },
          { id: '3', name: 'host3', status: 'offline' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('3')).toBeInTheDocument()
        expect(screen.getByText('Registered hosts')).toBeInTheDocument()
      })
    })

    it('should display online status', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        hosts: [
          { id: '1', status: 'online' },
          { id: '2', status: 'online' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Online')).toBeInTheDocument()
      })
    })

    it('should display offline status when hosts are offline', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        hosts: [
          { id: '1', status: 'online' },
          { id: '2', status: 'offline' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Online')).toBeInTheDocument()
        // Offline section should appear
        expect(screen.getByText('Offline')).toBeInTheDocument()
      })
    })

    it('should handle empty host list', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        hosts: [],
      })

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
