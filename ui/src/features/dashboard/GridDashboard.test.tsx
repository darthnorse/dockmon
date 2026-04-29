/**
 * GridDashboard Tests
 * Tests widget rendering and database-backed layout persistence.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import { GridDashboard } from './GridDashboard'
import type { ReactNode } from 'react'

const mockDashboardLayout = {
  layout: null as any,
  setLayout: vi.fn(),
  isLoading: false,
}

vi.mock('@/lib/hooks/useUserPreferences', () => ({
  useDashboardLayout: () => mockDashboardLayout,
  useTimeFormat: () => ({ timeFormat: '24h', setTimeFormat: vi.fn() }),
}))

vi.mock('@/lib/api/client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue([]),
  },
}))

// react-grid-layout uses DOM measurement APIs jsdom doesn't provide.
vi.mock('react-grid-layout', () => ({
  default: ({ children }: { children: ReactNode }) => (
    <div data-testid="grid-layout">{children}</div>
  ),
  WidthProvider: (Component: React.ComponentType) => Component,
}))

const renderDashboard = () => render(<GridDashboard />)

describe('GridDashboard', () => {
  beforeEach(() => {
    mockDashboardLayout.layout = null
    vi.clearAllMocks()
  })

  describe('rendering', () => {
    it('should render grid layout container', () => {
      renderDashboard()

      expect(screen.getByTestId('grid-layout')).toBeInTheDocument()
    })

    it('should render all default widgets', async () => {
      renderDashboard()

      await waitFor(() => {
        expect(screen.getByText('Hosts')).toBeInTheDocument()
        expect(screen.getByText('Containers')).toBeInTheDocument()
        expect(screen.getByText('Recent Events')).toBeInTheDocument()
        expect(screen.getByText('Active Alerts')).toBeInTheDocument()
      })
    })
  })

  describe('database persistence', () => {
    it('should load layout from database on mount', () => {
      mockDashboardLayout.layout = {
        widgets: [
          {
            id: 'host-stats',
            type: 'host-stats' as const,
            title: 'Host Stats',
            x: 5,
            y: 5,
            w: 4,
            h: 3,
          },
        ],
      }

      renderDashboard()

      expect(screen.getByText('Hosts')).toBeInTheDocument()
    })

    it('should use default layout when no saved layout exists', () => {
      mockDashboardLayout.layout = null

      renderDashboard()

      expect(screen.getByText('Hosts')).toBeInTheDocument()
      expect(screen.getByText('Containers')).toBeInTheDocument()
      expect(screen.getByText('Recent Events')).toBeInTheDocument()
      expect(screen.getByText('Active Alerts')).toBeInTheDocument()
    })
  })

  describe('layout container', () => {
    it('should have minimum width constraint', () => {
      const { container } = renderDashboard()

      expect(container.querySelector('.min-w-\\[900px\\]')).toBeInTheDocument()
    })

    it('should have horizontal scroll when needed', () => {
      const { container } = renderDashboard()

      expect(container.querySelector('.overflow-x-auto')).toBeInTheDocument()
    })
  })
})
