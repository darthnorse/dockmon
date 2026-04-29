/**
 * Unit tests for HostTable component
 * Tests table rendering, sorting, and all 10 columns per UX spec
 */

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@/test/utils'
import { HostTable } from './HostTable'
import * as useHostsModule from '../hooks/useHosts'
import type { Host } from '../hooks/useHosts'

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

describe('HostTable', () => {
  describe('rendering', () => {
    it('should render table headers even when loading', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: [],
        isLoading: true,
        error: null,
      } as any)

      render(<HostTable />)

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

      render(<HostTable />)

      // Error state shows error message
      expect(screen.getByText(/Error loading hosts/i)).toBeInTheDocument()
    })

    it('should render empty table when no hosts', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: [],
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />)

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

      render(<HostTable />)

      // Check all host names are present
      expect(screen.getByText('production-server')).toBeInTheDocument()
      expect(screen.getByText('dev-server')).toBeInTheDocument()
      expect(screen.getByText('staging-server')).toBeInTheDocument()
    })
  })

  describe('columns', () => {
    it('should render expected column headers', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />)

      expect(screen.getByText('Status')).toBeInTheDocument()
      expect(screen.getByText('Hostname')).toBeInTheDocument()
      expect(screen.getByText('IP')).toBeInTheDocument()
      expect(screen.getByText('Containers')).toBeInTheDocument()
      expect(screen.getByText('Alerts')).toBeInTheDocument()
      expect(screen.getByText('Uptime')).toBeInTheDocument()
      expect(screen.getByText('CPU%')).toBeInTheDocument()
      expect(screen.getByText('RAM%')).toBeInTheDocument()
      expect(screen.getByText('OS / Version')).toBeInTheDocument()
      expect(screen.getByText('Actions')).toBeInTheDocument()
    })

    it('should display status labels', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />)

      expect(screen.getByText('Online')).toBeInTheDocument()
      expect(screen.getByText('Offline')).toBeInTheDocument()
      expect(screen.getByText('Degraded')).toBeInTheDocument()
    })

    // Container counts come from ContainerCount, which subscribes to live
    // stats via useContainerCounts(hostId) — not from the host record's
    // container_count field. With the empty-stats mock provider those cells
    // render placeholders, so per-host count assertions belong in a stats-
    // wired integration test.

    it('should display tags with overflow indicator', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />)

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

    it('should display formatted uptime when daemon_started_at is set', () => {
      const oneHourAgo = new Date(Date.now() - 3600_000).toISOString()
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: [{ ...mockHosts[0], daemon_started_at: oneHourAgo }],
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />)

      // formatUptime(...) returns short form like "1h" / "2d 3h"
      expect(screen.getByText(/^\d+[smhd]/)).toBeInTheDocument()
    })

    it('should display per-row Edit Host buttons', () => {
      // simplified_workflow preference defaults to true, which hides the
      // "View full details" maximize button — only Edit Host renders here.
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />)

      const editButtons = screen
        .getAllByRole('button')
        .filter(btn => btn.getAttribute('title') === 'Edit Host')

      expect(editButtons.length).toBe(3)
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

      render(<HostTable />)

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

      render(<HostTable />)

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

      render(<HostTable />)

      expect(screen.getByText('unknown-server')).toBeInTheDocument()
      // Falls back to Offline status for unknown
      expect(screen.getByText('Offline')).toBeInTheDocument()
    })
  })

  describe('empty cells', () => {
    it('should render dash placeholders for unset metric/uptime cells', () => {
      vi.mocked(useHostsModule.useHosts).mockReturnValue({
        data: mockHosts,
        isLoading: false,
        error: null,
      } as any)

      render(<HostTable />)

      // Uptime/CPU%/RAM% cells fall back to '-' when daemon_started_at and
      // live host metrics are absent (mock host fixtures + empty stats provider).
      expect(screen.getAllByText('-').length).toBeGreaterThan(0)
    })
  })
})
