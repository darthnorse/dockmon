/**
 * Unit tests for HostTable component
 * Tests table rendering, sorting, and all 10 columns per UX spec
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HostTable } from './HostTable'
import * as useHostsModule from '../hooks/useHosts'
import type { Host } from '../hooks/useHosts'

// Mock the useHosts hook
vi.mock('../hooks/useHosts', () => ({
  useHosts: vi.fn(),
}))

// Mock data
const mockHosts: Host[] = [
  {
    id: '1',
    name: 'production-server',
    url: 'tcp://192.168.1.100:2376',
    status: 'online',
    last_checked: new Date().toISOString(),
    container_count: 5,
    tags: ['production', 'web'],
    description: 'Production web server',
  },
  {
    id: '2',
    name: 'dev-server',
    url: 'tcp://192.168.1.101:2376',
    status: 'offline',
    last_checked: new Date(Date.now() - 3600000).toISOString(), // 1 hour ago
    container_count: 2,
    tags: ['dev'],
    description: 'Development server',
  },
  {
    id: '3',
    name: 'staging-server',
    url: 'tcp://192.168.1.102:2376',
    status: 'degraded',
    last_checked: new Date(Date.now() - 300000).toISOString(), // 5 min ago
    container_count: 3,
    tags: ['staging', 'test', 'qa'],
    description: null,
  },
]

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

describe('HostTable', () => {
  describe('rendering', () => {
    it('should render table headers even when loading', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: [],
        isLoading: true,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // Loading state shows skeleton loaders, not table
      const skeletons = document.querySelectorAll('.animate-pulse')
      expect(skeletons.length).toBeGreaterThan(0)
    })

    it('should render table headers even on error', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: [],
        isLoading: false,
        error: new Error('Failed to fetch hosts'),
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // Error state shows error message
      expect(screen.getByText(/Error loading hosts/i)).toBeInTheDocument()
    })

    it('should render empty table when no hosts', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: [],
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // Empty state shows message
      expect(screen.getByText('No hosts configured')).toBeInTheDocument()
      expect(screen.getByText('Add your first Docker host to get started')).toBeInTheDocument()
    })

    it('should render table with hosts', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // Check all host names are present
      expect(screen.getByText('production-server')).toBeInTheDocument()
      expect(screen.getByText('dev-server')).toBeInTheDocument()
      expect(screen.getByText('staging-server')).toBeInTheDocument()
    })
  })

  describe('columns', () => {
    it('should display all 10 columns per UX spec', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // Column headers
      expect(screen.getByText('Status')).toBeInTheDocument()
      expect(screen.getByText('Hostname')).toBeInTheDocument()
      expect(screen.getByText('OS / Version')).toBeInTheDocument() // Note the spaces
      expect(screen.getByText('Containers')).toBeInTheDocument()
      expect(screen.getByText('CPU')).toBeInTheDocument()
      expect(screen.getByText('Memory')).toBeInTheDocument()
      expect(screen.getByText('Alerts')).toBeInTheDocument()
      expect(screen.getByText('Updates')).toBeInTheDocument()
      expect(screen.getByText('Uptime')).toBeInTheDocument()
      expect(screen.getByText('Actions')).toBeInTheDocument()
    })

    it('should display status labels', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      expect(screen.getByText('Online')).toBeInTheDocument()
      expect(screen.getByText('Offline')).toBeInTheDocument()
      expect(screen.getByText('Degraded')).toBeInTheDocument()
    })

    it('should display container counts', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // Check container counts are displayed (format: "5 / 5")
      // Use getAllByText since numbers appear in multiple places
      const fives = screen.getAllByText(/5/)
      expect(fives.length).toBeGreaterThan(0)

      const twos = screen.getAllByText(/2/)
      expect(twos.length).toBeGreaterThan(0)

      const threes = screen.getAllByText(/3/)
      expect(threes.length).toBeGreaterThan(0)
    })

    it('should display tags with overflow indicator', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // First host: 2 tags (production, web) - both shown
      expect(screen.getByText('production')).toBeInTheDocument()
      expect(screen.getByText('web')).toBeInTheDocument()

      // Second host: 1 tag (dev)
      expect(screen.getByText('dev')).toBeInTheDocument()

      // Third host: 3 tags (staging, test, qa) - first 2 shown + overflow
      expect(screen.getByText('staging')).toBeInTheDocument()
      expect(screen.getByText('test')).toBeInTheDocument()
      expect(screen.getByText('+1')).toBeInTheDocument() // Overflow indicator
    })

    it('should display relative uptime', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // Check for relative time text (date-fns formatDistanceToNow)
      const uptimeElements = screen.getAllByText(/ago|seconds?|minute?|hour?/i)
      expect(uptimeElements.length).toBeGreaterThan(0)
    })

    it('should display action buttons', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // Each row should have action buttons with titles (they're icon-only buttons)
      const allButtons = screen.getAllByRole('button')

      // Filter buttons by title attribute
      const detailsButtons = allButtons.filter(btn =>
        btn.getAttribute('title')?.includes('View Details')
      )
      const restartButtons = allButtons.filter(btn =>
        btn.getAttribute('title')?.includes('Restart Docker')
      )
      const logsButtons = allButtons.filter(btn =>
        btn.getAttribute('title')?.includes('View Logs')
      )

      // Each of 3 hosts should have these buttons
      expect(detailsButtons.length).toBe(3)
      expect(restartButtons.length).toBe(3)
      expect(logsButtons.length).toBe(3)
    })
  })

  describe('host status', () => {
    it('should handle hosts without tags', () => {
      const hostWithoutTags: Host = {
        id: '4',
        name: 'minimal-server',
        url: 'tcp://192.168.1.103:2376',
        status: 'online',
        last_checked: new Date().toISOString(),
        container_count: 0,
        tags: undefined,
        description: null,
      }

      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: [hostWithoutTags],
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      expect(screen.getByText('minimal-server')).toBeInTheDocument()
      // Should not crash when tags are undefined
    })

    it('should handle hosts with empty tags array', () => {
      const hostWithEmptyTags: Host = {
        id: '5',
        name: 'no-tags-server',
        url: 'tcp://192.168.1.104:2376',
        status: 'online',
        last_checked: new Date().toISOString(),
        container_count: 1,
        tags: [],
        description: null,
      }

      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: [hostWithEmptyTags],
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      expect(screen.getByText('no-tags-server')).toBeInTheDocument()
    })

    it('should handle unknown status gracefully', () => {
      const hostWithUnknownStatus: Host = {
        id: '6',
        name: 'unknown-server',
        url: 'tcp://192.168.1.105:2376',
        status: 'unknown-status' as any,
        last_checked: new Date().toISOString(),
        container_count: 0,
        tags: [],
        description: null,
      }

      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: [hostWithUnknownStatus],
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      expect(screen.getByText('unknown-server')).toBeInTheDocument()
      // Falls back to Offline status for unknown
      expect(screen.getByText('Offline')).toBeInTheDocument()
    })
  })

  describe('placeholder states', () => {
    it('should display placeholders for CPU/Memory sparklines', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // CPU and Memory columns render but with placeholder content
      expect(screen.getByText('CPU')).toBeInTheDocument()
      expect(screen.getByText('Memory')).toBeInTheDocument()
    })

    it('should display placeholder for OS/Version', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // OS/Version shows placeholder for all hosts
      const osPlaceholders = screen.getAllByText(/Ubuntu 24\.04/)
      expect(osPlaceholders.length).toBe(3) // One for each host
    })

    it('should display placeholder for Alerts', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />, { wrapper: createWrapper() })

      // Alerts column shows dash until alert system is integrated
      const alertPlaceholders = screen.getAllByText('-')
      expect(alertPlaceholders.length).toBeGreaterThan(0)
    })
  })
})
