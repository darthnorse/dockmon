/**
 * GridDashboard Tests
 * Tests widget rendering, database-backed layout persistence, and reset functionality
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { GridDashboard } from './GridDashboard'
import type { ReactNode } from 'react'

// Mock user preferences hook
const mockDashboardLayout = {
  layout: null as any,
  setLayout: vi.fn(),
  isLoading: false,
}

vi.mock('@/lib/hooks/useUserPreferences', () => ({
  useDashboardLayout: () => mockDashboardLayout,
}))

// Mock react-grid-layout to avoid DOM measurement issues in tests
vi.mock('react-grid-layout', () => ({
  default: ({ children }: { children: ReactNode }) => (
    <div data-testid="grid-layout">{children}</div>
  ),
  WidthProvider: (Component: React.ComponentType) => Component,
}))

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <GridDashboard />
    </QueryClientProvider>
  )
}

describe('GridDashboard', () => {
  beforeEach(() => {
    mockDashboardLayout.layout = null
    vi.clearAllMocks()
  })

  describe('rendering', () => {
    it('should render dashboard header', () => {
      renderDashboard()

      expect(screen.getByRole('heading', { name: /dashboard/i })).toBeInTheDocument()
      expect(screen.getByText(/monitor your docker containers and hosts/i)).toBeInTheDocument()
    })

    it('should render reset layout button', () => {
      renderDashboard()

      expect(screen.getByRole('button', { name: /reset layout/i })).toBeInTheDocument()
    })

    it('should render all default widgets', async () => {
      renderDashboard()

      await waitFor(() => {
        expect(screen.getByText('Host Stats')).toBeInTheDocument()
        expect(screen.getByText('Container Stats')).toBeInTheDocument()
        expect(screen.getByText('Recent Events')).toBeInTheDocument()
        expect(screen.getByText('Active Alerts')).toBeInTheDocument()
      })
    })

    it('should render grid layout container', () => {
      renderDashboard()

      expect(screen.getByTestId('grid-layout')).toBeInTheDocument()
    })
  })

  describe('database persistence', () => {
    it('should load layout from database on mount', () => {
      const customLayout = {
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

      mockDashboardLayout.layout = customLayout

      renderDashboard()

      // Should load from database (verify by checking that widget renders)
      expect(screen.getByText('Host Stats')).toBeInTheDocument()
    })

    it('should use default layout when no saved layout exists', () => {
      mockDashboardLayout.layout = null

      renderDashboard()

      // Should render all default widgets
      expect(screen.getByText('Host Stats')).toBeInTheDocument()
      expect(screen.getByText('Container Stats')).toBeInTheDocument()
      expect(screen.getByText('Recent Events')).toBeInTheDocument()
      expect(screen.getByText('Active Alerts')).toBeInTheDocument()
    })

    it('should call setLayout when reset button is clicked', () => {
      renderDashboard()

      const resetButton = screen.getByRole('button', { name: /reset layout/i })
      fireEvent.click(resetButton)

      // Should call setLayout with default layout
      expect(mockDashboardLayout.setLayout).toHaveBeenCalledWith(
        expect.objectContaining({
          widgets: expect.arrayContaining([
            expect.objectContaining({ id: 'host-stats' }),
            expect.objectContaining({ id: 'container-stats' }),
            expect.objectContaining({ id: 'recent-events' }),
            expect.objectContaining({ id: 'alert-summary' }),
          ]),
        })
      )
    })
  })

  describe('reset functionality', () => {
    it('should reset to default layout when clicking reset button', async () => {
      // Set custom layout
      const customLayout = {
        widgets: [
          {
            id: 'host-stats',
            type: 'host-stats' as const,
            title: 'Host Stats',
            x: 10,
            y: 10,
            w: 6,
            h: 4,
          },
        ],
      }
      mockDashboardLayout.layout = customLayout

      renderDashboard()

      const resetButton = screen.getByRole('button', { name: /reset layout/i })
      fireEvent.click(resetButton)

      // Should save default layout to database
      await waitFor(() => {
        expect(mockDashboardLayout.setLayout).toHaveBeenCalled()
      })
    })
  })

  describe('widget rendering', () => {
    it('should render widget components', async () => {
      renderDashboard()

      // All widgets should be rendered
      await waitFor(() => {
        expect(screen.getByText('Host Stats')).toBeInTheDocument()
        expect(screen.getByText('Container Stats')).toBeInTheDocument()
        expect(screen.getByText('Recent Events')).toBeInTheDocument()
        expect(screen.getByText('Active Alerts')).toBeInTheDocument()
      })
    })
  })

  describe('minimum width', () => {
    it('should have minimum width constraint', () => {
      const { container } = renderDashboard()

      const dashboardDiv = container.querySelector('.min-w-\\[900px\\]')
      expect(dashboardDiv).toBeInTheDocument()
    })

    it('should have horizontal scroll when needed', () => {
      const { container } = renderDashboard()

      const dashboardDiv = container.querySelector('.overflow-x-auto')
      expect(dashboardDiv).toBeInTheDocument()
    })
  })
})
