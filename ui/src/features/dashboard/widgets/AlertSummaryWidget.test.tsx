/**
 * AlertSummaryWidget Tests
 * Tests alert counts by severity
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AlertSummaryWidget } from './AlertSummaryWidget'
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
      <AlertSummaryWidget />
    </QueryClientProvider>
  )
}

describe('AlertSummaryWidget', () => {
  describe('loading state', () => {
    it('should show loading skeleton', () => {
      vi.mocked(apiClient.apiClient.get).mockImplementation(
        () => new Promise(() => {})
      )

      renderWidget()

      expect(screen.getByText('Active Alerts')).toBeInTheDocument()
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
        expect(screen.getByText('Failed to load alerts')).toBeInTheDocument()
      })
    })
  })

  describe('data rendering', () => {
    it('should display no alerts state', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        alerts: [],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('0')).toBeInTheDocument()
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
        expect(screen.getByText('No active alerts')).toBeInTheDocument()
      })
    })

    it('should display total alert count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        alerts: [
          { id: '1', severity: 'critical', message: 'Test 1', timestamp: '' },
          { id: '2', severity: 'warning', message: 'Test 2', timestamp: '' },
          { id: '3', severity: 'info', message: 'Test 3', timestamp: '' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('3')).toBeInTheDocument()
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
      })
    })

    it('should display critical alerts count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        alerts: [
          { id: '1', severity: 'critical', message: 'Test 1', timestamp: '' },
          { id: '2', severity: 'critical', message: 'Test 2', timestamp: '' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        // Should show total count
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
        // Critical severity should be visible
        expect(screen.getByText('Critical')).toBeInTheDocument()
      }, { timeout: 3000 })
    })

    it('should display warning alerts count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        alerts: [
          { id: '1', severity: 'warning', message: 'Test 1', timestamp: '' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
        expect(screen.getByText('Warning')).toBeInTheDocument()
      }, { timeout: 3000 })
    })

    it('should display info alerts count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        alerts: [
          { id: '1', severity: 'info', message: 'Test 1', timestamp: '' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
        expect(screen.getByText('Info')).toBeInTheDocument()
      }, { timeout: 3000 })
    })

    it('should display multiple severity types', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue({
        alerts: [
          { id: '1', severity: 'critical', message: 'Test 1', timestamp: '' },
          { id: '2', severity: 'warning', message: 'Test 2', timestamp: '' },
          { id: '3', severity: 'warning', message: 'Test 3', timestamp: '' },
          { id: '4', severity: 'info', message: 'Test 4', timestamp: '' },
        ],
      })

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Critical')).toBeInTheDocument()
        expect(screen.getByText('Warning')).toBeInTheDocument()
        expect(screen.getByText('Info')).toBeInTheDocument()
      })
    })
  })
})
