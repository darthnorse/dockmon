/**
 * ContainerTable Tests
 * Tests table rendering, sorting, filtering, and container actions
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@/test/utils'
import { ContainerTable } from './ContainerTable'
import * as apiClient from '@/lib/api/client'

// Mock toast
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/lib/api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

function renderTable() {
  return render(<ContainerTable />)
}

const mockContainers = [
  {
    id: 'container-1',
    name: 'nginx',
    image: 'nginx:latest',
    state: 'running' as const,
    status: 'Up 2 hours',
    created: '2025-01-07T10:00:00Z',
    ports: [],
    labels: {},
    host_id: 'host-1',
    host_name: 'host1',
  },
  {
    id: 'container-2',
    name: 'postgres',
    image: 'postgres:14',
    state: 'stopped' as const,
    status: 'Exited (0) 5 minutes ago',
    created: '2025-01-07T09:00:00Z',
    ports: [],
    labels: {},
    host_id: 'host-2',
    host_name: 'host2',
  },
]

describe('ContainerTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('loading state', () => {
    it('should show loading skeletons', () => {
      vi.mocked(apiClient.apiClient.get).mockImplementation(
        () => new Promise(() => {})
      )

      renderTable()

      const skeletons = document.querySelectorAll('.animate-pulse')
      expect(skeletons.length).toBeGreaterThan(0)
    })
  })

  describe('error state', () => {
    it('should show error message when API fails', async () => {
      vi.mocked(apiClient.apiClient.get).mockRejectedValue(
        new Error('Network error')
      )

      renderTable()

      await waitFor(() => {
        expect(screen.getByText(/failed to load containers/i)).toBeInTheDocument()
      })
    })
  })

  describe('data rendering', () => {
    it('should render container rows', async () => {
      // Backend returns array directly, not wrapped in object
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
        expect(screen.getByText('postgres')).toBeInTheDocument()
      })
    })

    it('should render container status badges', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('Running')).toBeInTheDocument()
        expect(screen.getByText('Exited')).toBeInTheDocument()
      })
    })

    it('should render host names', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('host1')).toBeInTheDocument()
        expect(screen.getByText('host2')).toBeInTheDocument()
      })
    })

    it('should show empty state when no containers', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([])

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('No containers found')).toBeInTheDocument()
      })
    })
  })

  describe('search functionality', () => {
    it('should render search input', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/search containers/i)).toBeInTheDocument()
      })
    })

    it('should show container count', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('2 container(s)')).toBeInTheDocument()
      })
    })
  })

  describe('container actions', () => {
    it('should show start button for stopped containers', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([mockContainers[1]]) // Stopped container

      renderTable()

      await waitFor(() => {
        const startButton = screen.getByTitle('Start container')
        expect(startButton).toBeInTheDocument()
      })
    })

    it('should show stop button for running containers', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([mockContainers[0]]) // Running container

      renderTable()

      await waitFor(() => {
        const stopButton = screen.getByTitle('Stop container')
        expect(stopButton).toBeInTheDocument()
      })
    })

    it('should show restart button for running containers', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([mockContainers[0]]) // Running container

      renderTable()

      await waitFor(() => {
        const restartButton = screen.getByTitle('Restart container')
        expect(restartButton).toBeInTheDocument()
      })
    })

    it('should call API with host_id and container_id when starting container', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([mockContainers[1]]) // Stopped container
      vi.mocked(apiClient.apiClient.post).mockResolvedValue({})

      renderTable()

      await waitFor(() => {
        const startButton = screen.getByTitle('Start container')
        fireEvent.click(startButton)
      })

      await waitFor(() => {
        // Endpoint now requires both host_id and container_id
        expect(apiClient.apiClient.post).toHaveBeenCalledWith(
          '/hosts/host-2/containers/container-2/start',
          {}
        )
      })
    })

    it('should disable action buttons when host_id is missing', async () => {
      const containerWithoutHost = { ...mockContainers[0], host_id: undefined }
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([containerWithoutHost])

      renderTable()

      await waitFor(() => {
        const stopButton = screen.getByTitle('Stop container')
        expect(stopButton).toBeDisabled()
      })
    })
  })

  describe('sorting', () => {
    it('should render sortable column headers', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        // Name and Status columns should be sortable
        const nameHeader = screen.getByRole('button', { name: /name/i })
        const statusHeader = screen.getByRole('button', { name: /status/i })
        expect(nameHeader).toBeInTheDocument()
        expect(statusHeader).toBeInTheDocument()
      })
    })
  })

  describe('network column', () => {
    it('shows download and upload rates, keeps lifetime totals in the tooltip, and dashes a stopped container', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([
        { ...mockContainers[0], net_bytes_per_sec: 1.5 * 1024 * 1024 + 2048, net_rx_bytes_per_sec: 1.5 * 1024 * 1024,
          net_tx_bytes_per_sec: 2048, network_rx: 1536, network_tx: 2 * 1024 * 1024 },
        { ...mockContainers[1], net_bytes_per_sec: 999999, net_rx_bytes_per_sec: 999999, net_tx_bytes_per_sec: 0,
          network_rx: 999999, network_tx: 999999 },
      ])

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('Network')).toBeInTheDocument()
      })
      const cells = screen.getAllByTestId('network-io')
      expect(cells).toHaveLength(1)
      expect(cells[0]).toHaveTextContent('1.5 MB/s')
      expect(cells[0]).toHaveTextContent('2.0 KB/s')
      expect(cells[0]).not.toHaveTextContent('1.5 KB ')
      expect(cells[0]).toHaveAttribute('title', 'Received 1.5 KB / Sent 2.0 MB since start')
    })

    it('shows the rates even before lifetime counters arrive', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([
        { ...mockContainers[0], net_bytes_per_sec: 3072, net_rx_bytes_per_sec: 2048, net_tx_bytes_per_sec: 1024 },
      ])

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })
      expect(screen.getByTestId('network-io')).toHaveTextContent('2.0 KB/s')
      expect(screen.getByTestId('network-io')).toHaveTextContent('1.0 KB/s')
    })

    it('shows a dash when a running container has no network data yet', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue([mockContainers[0]])

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })
      expect(screen.queryByTestId('network-io')).not.toBeInTheDocument()
    })
  })

  describe('table structure', () => {
    it('should render table with proper columns', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('Uptime')).toBeInTheDocument()
        expect(screen.getByText('Host')).toBeInTheDocument()
        expect(screen.getByText('Actions')).toBeInTheDocument()
      })
    })
  })
})
