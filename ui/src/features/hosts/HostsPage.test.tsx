/**
 * Unit tests for HostsPage component
 * Tests page layout, modal integration, and user interactions
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HostsPage } from './HostsPage'
import * as useHostsModule from './hooks/useHosts'

// Mock the useHosts hook
vi.mock('./hooks/useHosts', () => ({
  useHosts: vi.fn(),
}))

// Mock HostTable component
vi.mock('./components/HostTable', () => ({
  HostTable: () => <div data-testid="host-table">HostTable Component</div>,
}))

// Mock HostModal component
vi.mock('./components/HostModal', () => ({
  HostModal: ({ isOpen, onClose }: any) =>
    isOpen ? (
      <div data-testid="host-modal">
        <button onClick={onClose}>Close Modal</button>
      </div>
    ) : null,
}))

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe('HostsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // Mock useHosts to return empty array
    vi.mocked(useHostsModule.useHosts).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as any)
  })

  describe('page layout', () => {
    it('should render page header', () => {
      render(<HostsPage />, { wrapper: createWrapper() })

      expect(screen.getByText('Hosts')).toBeInTheDocument()
      expect(screen.getByText(/manage your docker hosts and connections/i)).toBeInTheDocument()
    })

    it('should render search bar', () => {
      render(<HostsPage />, { wrapper: createWrapper() })

      expect(screen.getByPlaceholderText(/search hosts/i)).toBeInTheDocument()
    })

    it('should render add host button', () => {
      render(<HostsPage />, { wrapper: createWrapper() })

      expect(screen.getByRole('button', { name: /add host/i })).toBeInTheDocument()
    })

    it('should render HostTable component', () => {
      render(<HostsPage />, { wrapper: createWrapper() })

      expect(screen.getByTestId('host-table')).toBeInTheDocument()
    })
  })

  describe('add host flow', () => {
    it('should open modal when add host button is clicked', async () => {
      const user = userEvent.setup()

      render(<HostsPage />, { wrapper: createWrapper() })

      // Modal should not be visible initially
      expect(screen.queryByTestId('host-modal')).not.toBeInTheDocument()

      // Click add host button
      const addButton = screen.getByRole('button', { name: /add host/i })
      await user.click(addButton)

      // Modal should now be visible
      expect(screen.getByTestId('host-modal')).toBeInTheDocument()
    })

    it('should close modal when onClose is called', async () => {
      const user = userEvent.setup()

      render(<HostsPage />, { wrapper: createWrapper() })

      // Open modal
      const addButton = screen.getByRole('button', { name: /add host/i })
      await user.click(addButton)

      expect(screen.getByTestId('host-modal')).toBeInTheDocument()

      // Close modal
      const closeButton = screen.getByText('Close Modal')
      await user.click(closeButton)

      expect(screen.queryByTestId('host-modal')).not.toBeInTheDocument()
    })

    it('should reset selected host when opening add modal', async () => {
      const user = userEvent.setup()

      render(<HostsPage />, { wrapper: createWrapper() })

      // Open modal for adding
      const addButton = screen.getByRole('button', { name: /add host/i })
      await user.click(addButton)

      expect(screen.getByTestId('host-modal')).toBeInTheDocument()

      // Close modal
      const closeButton = screen.getByText('Close Modal')
      await user.click(closeButton)

      // Open modal again - should be in "add" mode (selectedHost is null)
      await user.click(addButton)
      expect(screen.getByTestId('host-modal')).toBeInTheDocument()
    })
  })

  describe('search functionality', () => {
    it('should update search query on input', async () => {
      const user = userEvent.setup()

      render(<HostsPage />, { wrapper: createWrapper() })

      const searchInput = screen.getByPlaceholderText(/search hosts/i)
      await user.type(searchInput, 'production')

      expect(searchInput).toHaveValue('production')
    })

    it('should allow clearing search input', async () => {
      const user = userEvent.setup()

      render(<HostsPage />, { wrapper: createWrapper() })

      const searchInput = screen.getByPlaceholderText(/search hosts/i)
      await user.type(searchInput, 'production')
      expect(searchInput).toHaveValue('production')

      await user.clear(searchInput)
      expect(searchInput).toHaveValue('')
    })
  })

  describe('modal state management', () => {
    it('should maintain modal state correctly', async () => {
      const user = userEvent.setup()

      render(<HostsPage />, { wrapper: createWrapper() })

      // Initially closed
      expect(screen.queryByTestId('host-modal')).not.toBeInTheDocument()

      // Open modal
      const addButton = screen.getByRole('button', { name: /add host/i })
      await user.click(addButton)
      expect(screen.getByTestId('host-modal')).toBeInTheDocument()

      // Close modal
      const closeButton = screen.getByText('Close Modal')
      await user.click(closeButton)
      expect(screen.queryByTestId('host-modal')).not.toBeInTheDocument()

      // Re-open modal
      await user.click(addButton)
      expect(screen.getByTestId('host-modal')).toBeInTheDocument()
    })
  })

  describe('page structure', () => {
    it('should have proper container layout', () => {
      const { container } = render(<HostsPage />, { wrapper: createWrapper() })

      // Check that a container with proper classes exists
      const pageContainer = container.querySelector('.container')
      expect(pageContainer).toBeInTheDocument()
      expect(pageContainer).toHaveClass('mx-auto')
    })

    it('should render all main sections', () => {
      render(<HostsPage />, { wrapper: createWrapper() })

      // Header section
      expect(screen.getByText('Hosts')).toBeInTheDocument()

      // Search and action bar (implicitly tested by search input and button)
      expect(screen.getByPlaceholderText(/search hosts/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /add host/i })).toBeInTheDocument()

      // Table section
      expect(screen.getByTestId('host-table')).toBeInTheDocument()
    })
  })

  describe('accessibility', () => {
    it('should have accessible button labels', () => {
      render(<HostsPage />, { wrapper: createWrapper() })

      const addButton = screen.getByRole('button', { name: /add host/i })
      expect(addButton).toBeInTheDocument()
    })

    it('should have accessible search input', () => {
      render(<HostsPage />, { wrapper: createWrapper() })

      const searchInput = screen.getByPlaceholderText(/search hosts/i)
      expect(searchInput).toHaveAttribute('type', 'text')
    })
  })
})
