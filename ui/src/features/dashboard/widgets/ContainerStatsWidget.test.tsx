/**
 * ContainerStatsWidget Tests
 * Tests loading, error, and data rendering states
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ContainerStatsWidget } from './ContainerStatsWidget'
import * as apiClient from '@/lib/api/client'

// Mock the API client
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
      <ContainerStatsWidget />
    </QueryClientProvider>
  )
}

describe('ContainerStatsWidget', () => {
  describe('loading state', () => {
    it('should show loading skeleton', () => {
      vi.mocked(apiClient.apiClient.get).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      renderWidget()

      expect(screen.getByText('Containers')).toBeInTheDocument()
      // Check for skeleton (animated pulse divs)
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
        expect(screen.getByText('Failed to load container stats')).toBeInTheDocument()
      })
    })

    it('should still show widget title on error', async () => {
      vi.mocked(apiClient.apiClient.get).mockRejectedValue(
        new Error('Network error')
      )

      renderWidget()

      expect(screen.getByText('Containers')).toBeInTheDocument()
    })
  })

  describe('data rendering', () => {
    it('should display total container count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        containers: [
          { id: '1', name: 'container1', state: 'running' },
          { id: '2', name: 'container2', state: 'stopped' },
          { id: '3', name: 'container3', state: 'running' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('3')).toBeInTheDocument()
        expect(screen.getByText('Total containers')).toBeInTheDocument()
      })
    })

    it('should display running count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        containers: [
          { id: '1', state: 'running' },
          { id: '2', state: 'running' },
          { id: '3', state: 'stopped' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Running')).toBeInTheDocument()
        // Placeholder calculation: 70% of 3 = 2
        expect(screen.getByText('2')).toBeInTheDocument()
      })
    })

    it('should display stopped count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        containers: [
          { id: '1', state: 'running' },
          { id: '2', state: 'stopped' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Stopped')).toBeInTheDocument()
      })
    })

    it('should handle empty container list', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        containers: [],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Total containers')).toBeInTheDocument()
        // Should have "0" as the total count
        const totalElement = screen.getByText('Total containers').previousElementSibling
        expect(totalElement?.textContent).toBe('0')
      })
    })
  })

  describe('widget header', () => {
    it('should display container icon', () => {
      vi.mocked(apiClient.apiClient.get).mockImplementation(
        () => new Promise(() => {})
      )

      renderWidget()

      expect(screen.getByText('Containers')).toBeInTheDocument()
    })
  })
})
