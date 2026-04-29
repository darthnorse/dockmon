/**
 * AlertSummaryWidget Tests
 * Tests alert counts by severity
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import { AlertSummaryWidget } from './AlertSummaryWidget'
import * as apiClient from '@/lib/api/client'
import type { AlertStats } from '@/types/alerts'

vi.mock('@/lib/api/client', () => ({
  apiClient: {
    get: vi.fn(),
  },
}))

const renderWidget = () => render(<AlertSummaryWidget />)

const makeStats = (overrides: Partial<AlertStats> = {}): AlertStats => ({
  total: 0,
  by_state: { open: 0, snoozed: 0, resolved: 0 },
  by_severity: { critical: 0, error: 0, warning: 0 },
  ...overrides,
})

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
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(makeStats())

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('0')).toBeInTheDocument()
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
        expect(screen.getByText('No active alerts')).toBeInTheDocument()
      })
    })

    it('should display total alert count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(
        makeStats({
          total: 3,
          by_state: { open: 3, snoozed: 0, resolved: 0 },
          by_severity: { critical: 1, error: 1, warning: 1 },
        })
      )

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('3')).toBeInTheDocument()
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
      })
    })

    it('should display critical alerts count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(
        makeStats({
          total: 2,
          by_state: { open: 2, snoozed: 0, resolved: 0 },
          by_severity: { critical: 2, error: 0, warning: 0 },
        })
      )

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
        expect(screen.getByText('Critical')).toBeInTheDocument()
      })
    })

    it('should display warning alerts count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(
        makeStats({
          total: 1,
          by_state: { open: 1, snoozed: 0, resolved: 0 },
          by_severity: { critical: 0, error: 0, warning: 1 },
        })
      )

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
        expect(screen.getByText('Warning')).toBeInTheDocument()
      })
    })

    it('should display error alerts count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(
        makeStats({
          total: 1,
          by_state: { open: 1, snoozed: 0, resolved: 0 },
          by_severity: { critical: 0, error: 1, warning: 0 },
        })
      )

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Active alerts')).toBeInTheDocument()
        expect(screen.getByText('Error')).toBeInTheDocument()
      })
    })

    it('should display multiple severity types', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(
        makeStats({
          total: 4,
          by_state: { open: 4, snoozed: 0, resolved: 0 },
          by_severity: { critical: 1, error: 1, warning: 2 },
        })
      )

      renderWidget()

      await waitFor(() => {
        expect(screen.getByText('Critical')).toBeInTheDocument()
        expect(screen.getByText('Error')).toBeInTheDocument()
        expect(screen.getByText('Warning')).toBeInTheDocument()
      })
    })
  })
})
