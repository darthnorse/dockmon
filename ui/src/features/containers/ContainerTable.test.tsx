/**
 * ContainerTable Tests
 * Tests table rendering, sorting, filtering, and container actions
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
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
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ContainerTable />
    </QueryClientProvider>
  )
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

    it('should render container images', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('nginx:latest')).toBeInTheDocument()
        expect(screen.getByText('postgres:14')).toBeInTheDocument()
      })
    })

    it('should render container status badges', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        expect(screen.getByText('Running')).toBeInTheDocument()
        expect(screen.getByText('Stopped')).toBeInTheDocument()
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

  describe('table structure', () => {
    it('should render table with proper columns', async () => {
      vi.mocked(apiClient.apiClient.get).mockResolvedValue(mockContainers)

      renderTable()

      await waitFor(() => {
        // Check column headers
        expect(screen.getByText('Image')).toBeInTheDocument()
        expect(screen.getByText('Uptime')).toBeInTheDocument()
        expect(screen.getByText('Host')).toBeInTheDocument()
        expect(screen.getByText('Actions')).toBeInTheDocument()
      })
    })
  })
})
