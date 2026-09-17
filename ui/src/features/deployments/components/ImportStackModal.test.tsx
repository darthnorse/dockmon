import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { ImportStackModal } from './ImportStackModal'
import * as useDeploymentsModule from '../hooks/useDeployments'
import * as useHostsModule from '@/features/hosts/hooks/useHosts'

vi.mock('../hooks/useDeployments', () => ({
  useImportDeployment: vi.fn(),
  useScanComposeDirs: vi.fn(),
  useReadComposeFile: vi.fn(),
  useRunningProjects: vi.fn(),
  useGenerateFromContainers: vi.fn(),
}))

vi.mock('@/features/hosts/hooks/useHosts', () => ({
  useHosts: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

vi.mock('@/lib/api/client', () => ({
  apiClient: {
    get: vi.fn().mockResolvedValue({ is_container_mode: false }),
  },
}))

const mockComposeFiles = [
  {
    path: '/opt/stacks/nginx/docker-compose.yml',
    project_name: 'nginx',
    services: ['web', 'proxy'],
  },
  {
    path: '/opt/stacks/redis/docker-compose.yml',
    project_name: 'redis',
    services: ['redis'],
  },
  {
    path: '/opt/stacks/postgres/docker-compose.yml',
    project_name: 'postgres',
    services: ['db', 'backup'],
  },
]

const mockHosts = [
  {
    id: 'host-1',
    name: 'Agent Host 1',
    connection_type: 'agent',
    status: 'online',
  },
  {
    id: 'host-2',
    name: 'Agent Host 2',
    connection_type: 'agent',
    status: 'online',
  },
]

describe('ImportStackModal', () => {
  const mockOnClose = vi.fn()
  const mockOnSuccess = vi.fn()
  const mockScanMutateAsync = vi.fn()
  const mockReadMutateAsync = vi.fn()
  const mockImportMutateAsync = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()

    vi.mocked(useHostsModule.useHosts).mockReturnValue({
      data: mockHosts,
      isLoading: false,
    } as any)

    vi.mocked(useDeploymentsModule.useScanComposeDirs).mockReturnValue({
      mutateAsync: mockScanMutateAsync,
      isPending: false,
    } as any)

    vi.mocked(useDeploymentsModule.useReadComposeFile).mockReturnValue({
      mutateAsync: mockReadMutateAsync,
      isPending: false,
    } as any)

    vi.mocked(useDeploymentsModule.useImportDeployment).mockReturnValue({
      mutateAsync: mockImportMutateAsync,
      isPending: false,
    } as any)

    vi.mocked(useDeploymentsModule.useRunningProjects).mockReturnValue({
      data: [],
      isLoading: false,
    } as any)

    vi.mocked(useDeploymentsModule.useGenerateFromContainers).mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as any)
  })

  describe('Browse Host tab', () => {
    it('should show host selection dropdown in Browse mode', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })

      render(
        <ImportStackModal isOpen={true} onClose={mockOnClose} onSuccess={mockOnSuccess} />)

      const browseTab = screen.getByRole('button', { name: /browse host/i })
      await user.click(browseTab)

      expect(screen.getByText(/select agent host/i)).toBeInTheDocument()
    })

    it('should scan host and display compose files', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })

      mockScanMutateAsync.mockResolvedValue({
        success: true,
        compose_files: mockComposeFiles,
      })

      render(
        <ImportStackModal isOpen={true} onClose={mockOnClose} onSuccess={mockOnSuccess} />)

      const browseTab = screen.getByRole('button', { name: /browse host/i })
      await user.click(browseTab)

      const hostSelect = screen.getByLabelText(/select agent host/i)
      await user.click(hostSelect)
      const hostOption = screen.getByRole('option', { name: /agent host 1/i })
      await user.click(hostOption)

      const scanButton = screen.getByRole('button', { name: /scan for compose files/i })
      await user.click(scanButton)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
        expect(screen.getByText('redis')).toBeInTheDocument()
        expect(screen.getByText('postgres')).toBeInTheDocument()
      })
    })
  })

  describe('Checkbox selection', () => {
    async function setupWithFiles(user: ReturnType<typeof userEvent.setup>) {
      mockScanMutateAsync.mockResolvedValue({
        success: true,
        compose_files: mockComposeFiles,
      })

      render(
        <ImportStackModal isOpen={true} onClose={mockOnClose} onSuccess={mockOnSuccess} />)

      const browseTab = screen.getByRole('button', { name: /browse host/i })
      await user.click(browseTab)

      const hostSelect = screen.getByLabelText(/select agent host/i)
      await user.click(hostSelect)
      const hostOption = screen.getByRole('option', { name: /agent host 1/i })
      await user.click(hostOption)

      const scanButton = screen.getByRole('button', { name: /scan for compose files/i })
      await user.click(scanButton)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })
    }

    it('should show Select All checkbox after scan', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      await setupWithFiles(user)

      expect(screen.getByLabelText(/select all/i)).toBeInTheDocument()
      expect(screen.getByText(/select all \(3\)/i)).toBeInTheDocument()
    })

    it('should toggle individual file selection', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      await setupWithFiles(user)

      // Get all checkboxes (first is Select All, rest are individual files)
      const checkboxes = screen.getAllByRole('checkbox')
      expect(checkboxes).toHaveLength(4) // 1 select all + 3 files

      await user.click(checkboxes[1])

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /import selected \(1\)/i })).toBeInTheDocument()
      })

      await user.click(checkboxes[2])

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /import selected \(2\)/i })).toBeInTheDocument()
      })
    })

    it('should select all files when Select All is clicked', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      await setupWithFiles(user)

      const selectAllCheckbox = screen.getByLabelText(/select all/i)
      await user.click(selectAllCheckbox)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /import selected \(3\)/i })).toBeInTheDocument()
      })

      const checkboxes = screen.getAllByRole('checkbox')
      checkboxes.forEach((checkbox) => {
        expect(checkbox).toBeChecked()
      })
    })

    it('should deselect all files when Select All is unchecked', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      await setupWithFiles(user)

      const selectAllCheckbox = screen.getByLabelText(/select all/i)
      await user.click(selectAllCheckbox)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /import selected \(3\)/i })).toBeInTheDocument()
      })

      await user.click(selectAllCheckbox)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /^import stack$/i })).toBeInTheDocument()
      })

      const checkboxes = screen.getAllByRole('checkbox')
      checkboxes.forEach((checkbox) => {
        expect(checkbox).not.toBeChecked()
      })
    })

    it('should clear selection when scanning a different host', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      await setupWithFiles(user)

      const selectAllCheckbox = screen.getByLabelText(/select all/i)
      await user.click(selectAllCheckbox)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /import selected \(3\)/i })).toBeInTheDocument()
      })

      mockScanMutateAsync.mockResolvedValue({
        success: true,
        compose_files: [
          {
            path: '/data/app/docker-compose.yml',
            project_name: 'app',
            services: ['web'],
          },
        ],
      })

      // Scan again (simulates switching host or rescanning)
      const scanButton = screen.getByRole('button', { name: /scan for compose files/i })
      await user.click(scanButton)

      await waitFor(() => {
        expect(screen.getByText('app')).toBeInTheDocument()
      })

      expect(screen.getByRole('button', { name: /^import stack$/i })).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /import selected/i })).not.toBeInTheDocument()
    })
  })

  describe('Batch import', () => {
    async function setupWithFilesSelected(user: ReturnType<typeof userEvent.setup>) {
      mockScanMutateAsync.mockResolvedValue({
        success: true,
        compose_files: mockComposeFiles,
      })

      render(
        <ImportStackModal isOpen={true} onClose={mockOnClose} onSuccess={mockOnSuccess} />)

      const browseTab = screen.getByRole('button', { name: /browse host/i })
      await user.click(browseTab)

      const hostSelect = screen.getByLabelText(/select agent host/i)
      await user.click(hostSelect)
      const hostOption = screen.getByRole('option', { name: /agent host 1/i })
      await user.click(hostOption)

      const scanButton = screen.getByRole('button', { name: /scan for compose files/i })
      await user.click(scanButton)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const selectAllCheckbox = screen.getByLabelText(/select all/i)
      await user.click(selectAllCheckbox)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /import selected \(3\)/i })).toBeInTheDocument()
      })
    }

    it('should import all selected files sequentially', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      await setupWithFilesSelected(user)

      mockReadMutateAsync.mockResolvedValue({
        success: true,
        content: 'version: "3"\nservices:\n  web:\n    image: nginx',
      })

      mockImportMutateAsync.mockResolvedValue({
        success: true,
        deployments_created: [{ id: 'dep-1', name: 'test', host_id: 'host-1' }],
      })

      const importButton = screen.getByRole('button', { name: /import selected \(3\)/i })
      await user.click(importButton)

      await waitFor(() => {
        expect(mockReadMutateAsync).toHaveBeenCalledTimes(3)
        expect(mockImportMutateAsync).toHaveBeenCalledTimes(3)
      })

      await waitFor(() => {
        expect(screen.getByText(/successfully imported/i)).toBeInTheDocument()
      })
    })

    it('should accumulate errors and continue importing other files', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      await setupWithFilesSelected(user)

      mockReadMutateAsync
        .mockResolvedValueOnce({ success: false, error: 'File not found' })
        .mockResolvedValue({
          success: true,
          content: 'version: "3"\nservices:\n  web:\n    image: nginx',
        })

      mockImportMutateAsync.mockResolvedValue({
        success: true,
        deployments_created: [{ id: 'dep-1', name: 'test', host_id: 'host-1' }],
      })

      const importButton = screen.getByRole('button', { name: /import selected \(3\)/i })
      await user.click(importButton)

      await waitFor(() => {
        expect(mockImportMutateAsync).toHaveBeenCalledTimes(2)
      })

      await waitFor(() => {
        expect(screen.getByText(/successfully imported 2 stack/i)).toBeInTheDocument()
      })
      expect(screen.getByText(/File not found/)).toBeInTheDocument()
    })

    it('should disable buttons during batch import', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })
      await setupWithFilesSelected(user)

      let resolveImport: () => void
      mockReadMutateAsync.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveImport = () =>
              resolve({
                success: true,
                content: 'version: "3"',
              })
          })
      )

      const importButton = screen.getByRole('button', { name: /import selected \(3\)/i })
      await user.click(importButton)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled()
      })

      resolveImport!()
    })
  })

  describe('Modal behavior', () => {
    it('should reset state when modal closes', async () => {
      const user = userEvent.setup({ pointerEventsCheck: 0 })

      mockScanMutateAsync.mockResolvedValue({
        success: true,
        compose_files: mockComposeFiles,
      })

      const { rerender } = render(
        <ImportStackModal isOpen={true} onClose={mockOnClose} onSuccess={mockOnSuccess} />)

      const browseTab = screen.getByRole('button', { name: /browse host/i })
      await user.click(browseTab)

      const hostSelect = screen.getByLabelText(/select agent host/i)
      await user.click(hostSelect)
      const hostOption = screen.getByRole('option', { name: /agent host 1/i })
      await user.click(hostOption)

      const scanButton = screen.getByRole('button', { name: /scan for compose files/i })
      await user.click(scanButton)

      await waitFor(() => {
        expect(screen.getByText('nginx')).toBeInTheDocument()
      })

      const selectAllCheckbox = screen.getByLabelText(/select all/i)
      await user.click(selectAllCheckbox)

      rerender(<ImportStackModal isOpen={false} onClose={mockOnClose} onSuccess={mockOnSuccess} />)
      rerender(<ImportStackModal isOpen={true} onClose={mockOnClose} onSuccess={mockOnSuccess} />)

      expect(screen.getByPlaceholderText(/paste your docker-compose/i)).toBeInTheDocument()
    })
  })
})
