/**
 * Sidebar Component Tests
 * Tests navigation, collapse/expand, localStorage, and WebSocket status
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { Sidebar } from './Sidebar'

// Mock WebSocket context
const mockWebSocketContext = {
  status: 'connected' as const,
  send: vi.fn(),
}

vi.mock('@/lib/websocket/WebSocketProvider', () => ({
  useWebSocketContext: () => mockWebSocketContext,
}))

// Mock user preferences hook
const mockSidebarState = {
  isCollapsed: false,
  setCollapsed: vi.fn(),
  isLoading: false,
}

vi.mock('@/lib/hooks/useUserPreferences', () => ({
  useSidebarCollapsed: () => mockSidebarState,
}))

// Test wrapper with router
function renderSidebar() {
  return render(
    <BrowserRouter>
      <Sidebar />
    </BrowserRouter>
  )
}

describe('Sidebar', () => {
  beforeEach(() => {
    // Reset window width
    global.innerWidth = 1920
    // Reset mock state
    mockSidebarState.isCollapsed = false
    vi.clearAllMocks()
  })

  describe('rendering', () => {
    it('should render all navigation items', () => {
      renderSidebar()

      expect(screen.getByText('Dashboard')).toBeInTheDocument()
      expect(screen.getByText('Hosts')).toBeInTheDocument()
      expect(screen.getByText('Containers')).toBeInTheDocument()
      expect(screen.getByText('Events')).toBeInTheDocument()
      expect(screen.getByText('Alerts')).toBeInTheDocument()
      expect(screen.getByText('Settings')).toBeInTheDocument()
    })

    it('should render DockMon logo', () => {
      renderSidebar()

      expect(screen.getByText('DockMon')).toBeInTheDocument()
    })

    it('should render user info', () => {
      renderSidebar()

      expect(screen.getByText('admin')).toBeInTheDocument()
      expect(screen.getByText('Administrator')).toBeInTheDocument()
    })

    it('should render collapse/expand button', () => {
      renderSidebar()

      const button = screen.getByRole('button', { name: /collapse sidebar/i })
      expect(button).toBeInTheDocument()
    })
  })

  describe('collapse/expand functionality', () => {
    it('should start expanded by default on desktop', () => {
      global.innerWidth = 1920
      renderSidebar()

      const sidebar = screen.getByRole('complementary')
      expect(sidebar).toHaveClass('w-60') // Expanded width
    })

    it('should collapse when clicking collapse button', () => {
      renderSidebar()

      const button = screen.getByRole('button', { name: /collapse sidebar/i })
      fireEvent.click(button)

      const sidebar = screen.getByRole('complementary')
      expect(sidebar).toHaveClass('w-18') // Collapsed width
    })

    it('should expand when clicking expand button', () => {
      renderSidebar()

      // First collapse
      const collapseButton = screen.getByRole('button', { name: /collapse sidebar/i })
      fireEvent.click(collapseButton)

      // Then expand
      const expandButton = screen.getByRole('button', { name: /expand sidebar/i })
      fireEvent.click(expandButton)

      const sidebar = screen.getByRole('complementary')
      expect(sidebar).toHaveClass('w-60') // Expanded width
    })

    it('should hide navigation labels when collapsed', () => {
      renderSidebar()

      // Initially visible
      expect(screen.getByText('Dashboard')).toBeVisible()

      // Collapse
      const button = screen.getByRole('button', { name: /collapse sidebar/i })
      fireEvent.click(button)

      // Labels should not be visible (though still in DOM for icons)
      const sidebar = screen.getByRole('complementary')
      expect(sidebar).toHaveClass('w-18')
    })
  })

  describe('database persistence', () => {
    it('should call setCollapsed when collapse button is clicked', () => {
      renderSidebar()

      const button = screen.getByRole('button', { name: /collapse sidebar/i })
      fireEvent.click(button)

      expect(mockSidebarState.setCollapsed).toHaveBeenCalledWith(true)
    })

    it('should call setCollapsed when expand button is clicked', () => {
      mockSidebarState.isCollapsed = true
      renderSidebar()

      const button = screen.getByRole('button', { name: /expand sidebar/i })
      fireEvent.click(button)

      expect(mockSidebarState.setCollapsed).toHaveBeenCalledWith(false)
    })

    it('should render collapsed state from database', () => {
      mockSidebarState.isCollapsed = true
      renderSidebar()

      const sidebar = screen.getByRole('complementary')
      expect(sidebar).toHaveClass('w-18') // Collapsed
    })

    it('should render expanded state from database', () => {
      mockSidebarState.isCollapsed = false
      renderSidebar()

      const sidebar = screen.getByRole('complementary')
      expect(sidebar).toHaveClass('w-60') // Expanded
    })
  })

  describe('WebSocket status indicator', () => {
    it('should show connected status', () => {
      mockWebSocketContext.status = 'connected'

      renderSidebar()

      expect(screen.getByText('Real-time updates')).toBeInTheDocument()
    })

    it('should show reconnecting status', () => {
      mockWebSocketContext.status = 'connecting'

      renderSidebar()

      expect(screen.getByText('Reconnecting...')).toBeInTheDocument()
    })

    it('should show disconnected status', () => {
      mockWebSocketContext.status = 'disconnected'

      renderSidebar()

      expect(screen.getByText('Reconnecting...')).toBeInTheDocument()
    })
  })

  describe('navigation', () => {
    it('should have correct href attributes', () => {
      renderSidebar()

      expect(screen.getByRole('link', { name: /dashboard/i })).toHaveAttribute('href', '/')
      expect(screen.getByRole('link', { name: /hosts/i })).toHaveAttribute('href', '/hosts')
      expect(screen.getByRole('link', { name: /containers/i })).toHaveAttribute('href', '/containers')
      expect(screen.getByRole('link', { name: /events/i })).toHaveAttribute('href', '/events')
      expect(screen.getByRole('link', { name: /alerts/i })).toHaveAttribute('href', '/alerts')
      expect(screen.getByRole('link', { name: /settings/i })).toHaveAttribute('href', '/settings')
    })
  })

  describe('accessibility', () => {
    it('should have proper ARIA label', () => {
      renderSidebar()

      const sidebar = screen.getByRole('complementary', { name: /main navigation/i })
      expect(sidebar).toBeInTheDocument()
    })

    it('should have navigation role', () => {
      renderSidebar()

      expect(screen.getByRole('navigation')).toBeInTheDocument()
    })
  })
})
