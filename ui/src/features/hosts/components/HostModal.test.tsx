/**
 * Unit tests for HostModal component
 * Tests form validation, TLS toggle, TagInput integration, and submission
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@/test/utils'
import userEvent from '@testing-library/user-event'
import { HostModal } from './HostModal'
import * as useHostsModule from '../hooks/useHosts'
import * as useTagsModule from '@/lib/hooks/useTags'
import type { Host } from '../hooks/useHosts'

vi.mock('../hooks/useHosts', () => ({
  useAddHost: vi.fn(),
  useUpdateHost: vi.fn(),
  useDeleteHost: vi.fn(),
}))

vi.mock('@/lib/hooks/useTags', () => ({
  useTags: vi.fn(),
}))

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}))

// Add-mode renders an Agent (recommended) / Legacy tab pair. The host form
// (Host Name / Address / mTLS / etc.) lives in the Legacy tab, so add-mode
// tests must switch to it first; edit-mode renders the form directly.
async function openAddForm() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: /legacy/i }))
  return user
}

describe('HostModal', () => {
  const mockOnClose = vi.fn()
  const mockMutate = vi.fn()
  const mockMutateAsync = vi.fn().mockResolvedValue(undefined)

  beforeEach(() => {
    vi.clearAllMocks()
    mockMutateAsync.mockResolvedValue(undefined)

    // Mock useTags to return empty array
    vi.mocked(useTagsModule.useTags).mockReturnValue({
      data: [],
      isLoading: false,
    } as any)

    // Mock useAddHost
    vi.mocked(useHostsModule.useAddHost).mockReturnValue({
      mutate: mockMutate,
      mutateAsync: mockMutateAsync,
      isPending: false,
    } as any)

    // Mock useUpdateHost
    vi.mocked(useHostsModule.useUpdateHost).mockReturnValue({
      mutate: mockMutate,
      mutateAsync: mockMutateAsync,
      isPending: false,
    } as any)

    vi.mocked(useHostsModule.useDeleteHost).mockReturnValue({
      mutate: mockMutate,
      mutateAsync: mockMutateAsync,
      isPending: false,
    } as any)
  })

  describe('rendering', () => {
    it('should render add host modal', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)

      expect(screen.getByRole('heading', { name: /add host/i })).toBeInTheDocument()
      await openAddForm()
      expect(screen.getByLabelText(/host name/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/address.*endpoint/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/enable mtls/i)).toBeInTheDocument()
    })

    it('should render edit host modal with pre-filled data', () => {
      const existingHost: Host = {
        id: '1',
        name: 'production-server',
        url: 'tcp://192.168.1.100:2376',
        status: 'online',
        last_checked: new Date().toISOString(),
        container_count: 5,
        tags: ['production', 'web'],
        description: 'Production web server',
        security_status: null, // No mTLS
      }

      render(<HostModal isOpen={true} onClose={mockOnClose} host={existingHost} />)

      expect(screen.getByText('Edit Host')).toBeInTheDocument()
      expect(screen.getByDisplayValue('production-server')).toBeInTheDocument()
      expect(screen.getByDisplayValue('tcp://192.168.1.100:2376')).toBeInTheDocument()
      expect(screen.getByDisplayValue('Production web server')).toBeInTheDocument()
    })

    it('should not render when isOpen is false', () => {
      render(<HostModal isOpen={false} onClose={mockOnClose} host={null} />)

      expect(screen.queryByRole('heading', { name: /add host/i })).not.toBeInTheDocument()
    })
  })

  describe('form validation', () => {
    it('should require host name', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      const submitButton = screen.getByRole('button', { name: /add host/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(screen.getByText(/host name is required/i)).toBeInTheDocument()
      })

      expect(mockMutate).not.toHaveBeenCalled()
    })

    it('should require address/endpoint', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      const nameInput = screen.getByLabelText(/host name/i)
      await user.type(nameInput, 'test-server')

      const submitButton = screen.getByRole('button', { name: /add host/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(screen.getByText(/address\/endpoint is required/i)).toBeInTheDocument()
      })

      expect(mockMutate).not.toHaveBeenCalled()
    })

    it('should validate URL format', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      const nameInput = screen.getByLabelText(/host name/i)
      const urlInput = screen.getByLabelText(/address.*endpoint/i)

      await user.type(nameInput, 'test-server')
      await user.type(urlInput, 'invalid-url')

      const submitButton = screen.getByRole('button', { name: /add host/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(
          screen.getByText(/url must start with tcp:\/\/, unix:\/\/, http:\/\/, or https:\/\//i)
        ).toBeInTheDocument()
      })

      expect(mockMutate).not.toHaveBeenCalled()
    })

    it('should validate host name format', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      const nameInput = screen.getByLabelText(/host name/i)
      const urlInput = screen.getByLabelText(/address.*endpoint/i)

      await user.type(nameInput, '!invalid-name')
      await user.type(urlInput, 'tcp://localhost:2376')

      const submitButton = screen.getByRole('button', { name: /add host/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(screen.getByText(/host name contains invalid characters/i)).toBeInTheDocument()
      })

      expect(mockMutate).not.toHaveBeenCalled()
    })

    it('should enforce max length for host name', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      const nameInput = screen.getByLabelText(/host name/i)
      const urlInput = screen.getByLabelText(/address.*endpoint/i)

      // Generate a 101-character string
      const longName = 'a'.repeat(101)
      await user.type(nameInput, longName)
      await user.type(urlInput, 'tcp://localhost:2376')

      const submitButton = screen.getByRole('button', { name: /add host/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(
          screen.getByText(/host name must be less than 100 characters/i)
        ).toBeInTheDocument()
      })

      expect(mockMutate).not.toHaveBeenCalled()
    })

    it('should enforce max length for description', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      const nameInput = screen.getByLabelText(/host name/i)
      const urlInput = screen.getByLabelText(/address.*endpoint/i)
      const descriptionInput = screen.getByLabelText(/description/i)

      await user.type(nameInput, 'test-server')
      await user.type(urlInput, 'tcp://localhost:2376')

      // Generate a 1001-character string
      const longDescription = 'a'.repeat(1001)
      await user.type(descriptionInput, longDescription)

      const submitButton = screen.getByRole('button', { name: /add host/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(
          screen.getByText(/description must be less than 1000 characters/i)
        ).toBeInTheDocument()
      })

      expect(mockMutate).not.toHaveBeenCalled()
    })
  })

  describe('mTLS toggle', () => {
    it('should show mTLS fields when enabled', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      // mTLS fields should be hidden initially
      expect(screen.queryByLabelText(/ca certificate/i)).not.toBeInTheDocument()
      expect(screen.queryByLabelText(/client certificate/i)).not.toBeInTheDocument()
      expect(screen.queryByLabelText(/client.*key/i)).not.toBeInTheDocument()

      // Enable mTLS
      const mtlsToggle = screen.getByLabelText(/enable mtls/i)
      await user.click(mtlsToggle)

      // mTLS fields should now be visible
      await waitFor(() => {
        expect(screen.getByLabelText(/ca certificate/i)).toBeInTheDocument()
        expect(screen.getByLabelText(/client certificate/i)).toBeInTheDocument()
        expect(screen.getByLabelText(/client.*key/i)).toBeInTheDocument()
      })
    })

    it('should hide mTLS fields when disabled', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      // Enable mTLS
      const mtlsToggle = screen.getByLabelText(/enable mtls/i)
      await user.click(mtlsToggle)

      await waitFor(() => {
        expect(screen.getByLabelText(/ca certificate/i)).toBeInTheDocument()
      })

      // Disable mTLS
      await user.click(mtlsToggle)

      await waitFor(() => {
        expect(screen.queryByLabelText(/ca certificate/i)).not.toBeInTheDocument()
      })
    })

    it('should check mTLS checkbox for existing hosts with certificates', () => {
      const existingHost: Host = {
        id: '1',
        name: 'secure-server',
        url: 'tcp://192.168.1.100:2376',
        status: 'online',
        last_checked: new Date().toISOString(),
        container_count: 5,
        tags: [],
        description: null,
        security_status: 'secure', // Has mTLS
      }

      render(<HostModal isOpen={true} onClose={mockOnClose} host={existingHost} />)

      // mTLS checkbox should be checked
      const mtlsToggle = screen.getByLabelText(/enable mtls/i) as HTMLInputElement
      expect(mtlsToggle.checked).toBe(true)

      // Should show 3 masked placeholders (one for each cert field)
      const placeholders = screen.getAllByText(/uploaded — •••/i)
      expect(placeholders.length).toBe(3)

      // Should have 3 Replace buttons (one for each cert field)
      expect(screen.getAllByRole('button', { name: /replace/i }).length).toBe(3)
    })
  })

  // Tags are no longer managed in HostModal — they live in the host drawer
  // (see HostModal.tsx file header). TagInput tests removed.

  describe('form submission', () => {
    it('should submit valid form for adding host', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      const nameInput = screen.getByLabelText(/host name/i)
      const urlInput = screen.getByLabelText(/address.*endpoint/i)
      const descriptionInput = screen.getByLabelText(/description/i)

      await user.type(nameInput, 'new-server')
      await user.type(urlInput, 'tcp://192.168.1.200:2376')
      await user.type(descriptionInput, 'New test server')

      const submitButton = screen.getByRole('button', { name: /add host/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            name: 'new-server',
            url: 'tcp://192.168.1.200:2376',
            description: 'New test server',
          })
        )
      })
    })

    it('should submit valid form for updating host', async () => {
      const user = userEvent.setup()

      const existingHost: Host = {
        id: '1',
        name: 'production-server',
        url: 'tcp://192.168.1.100:2376',
        status: 'online',
        last_checked: new Date().toISOString(),
        container_count: 5,
        tags: ['production'],
        description: 'Original description',
        security_status: null,
      }

      render(<HostModal isOpen={true} onClose={mockOnClose} host={existingHost} />)

      const nameInput = screen.getByLabelText(/host name/i)
      await user.clear(nameInput)
      await user.type(nameInput, 'updated-server')

      const submitButton = screen.getByRole('button', { name: /update host/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            id: '1',
            config: expect.objectContaining({
              name: 'updated-server',
            }),
          })
        )
      })
    })

    it('should include mTLS certificates when mTLS is enabled', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      const nameInput = screen.getByLabelText(/host name/i)
      const urlInput = screen.getByLabelText(/address.*endpoint/i)

      await user.type(nameInput, 'secure-server')
      await user.type(urlInput, 'tcp://192.168.1.200:2376')

      // Enable mTLS
      const mtlsToggle = screen.getByLabelText(/enable mtls/i)
      await user.click(mtlsToggle)

      await waitFor(() => {
        expect(screen.getByLabelText(/ca certificate/i)).toBeInTheDocument()
      })

      // Fill in all three required certificates
      const caInput = screen.getByLabelText(/ca certificate/i) as HTMLTextAreaElement
      const certInput = screen.getByLabelText(/client certificate/i) as HTMLTextAreaElement
      const keyInput = screen.getByLabelText(/client.*key/i) as HTMLTextAreaElement

      await user.type(caInput, 'test-ca-cert')
      await user.type(certInput, 'test-client-cert')
      await user.type(keyInput, 'test-client-key')

      const submitButton = screen.getByRole('button', { name: /add host/i })
      await user.click(submitButton)

      await waitFor(() => {
        expect(mockMutateAsync).toHaveBeenCalledWith(
          expect.objectContaining({
            name: 'secure-server',
            url: 'tcp://192.168.1.200:2376',
            tls_ca: 'test-ca-cert',
            tls_cert: 'test-client-cert',
            tls_key: 'test-client-key',
          })
        )
      })
    })
  })

  describe('cancel behavior', () => {
    it('should close modal when cancel button is clicked', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      const cancelButton = screen.getByRole('button', { name: /cancel/i })
      await user.click(cancelButton)

      expect(mockOnClose).toHaveBeenCalled()
    })

    it('should close modal when X button is clicked', async () => {
      const user = userEvent.setup()

      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)

      const closeButton = screen.getByRole('button', { name: /close/i })
      await user.click(closeButton)

      expect(mockOnClose).toHaveBeenCalled()
    })
  })

  describe('loading state', () => {
    it('should show Saving text when form is submitting', async () => {
      // Make mutateAsync take a long time so we can catch the submitting state
      const slowMutateAsync = vi.fn(() => new Promise(resolve => setTimeout(resolve, 1000)))

      vi.mocked(useHostsModule.useAddHost).mockReturnValue({
        mutate: mockMutate,
        mutateAsync: slowMutateAsync,
        isPending: false,
      } as any)

      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      // Fill in minimal required fields
      const nameInput = screen.getByLabelText(/host name/i)
      const urlInput = screen.getByLabelText(/address.*endpoint/i)
      await user.type(nameInput, 'test-server')
      await user.type(urlInput, 'tcp://localhost:2376')

      // Submit the form
      const submitButton = screen.getByRole('button', { name: /add host/i })
      await user.click(submitButton)

      // Check that button shows "Saving..." and is disabled
      await waitFor(() => {
        const savingButton = screen.getByRole('button', { name: /saving/i })
        expect(savingButton).toBeDisabled()
      })
    })
  })

  describe('test connection', () => {
    it('should show test connection button for non-mTLS connections', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      await openAddForm()

      // Should have Test Connection button when mTLS is disabled
      expect(screen.getByRole('button', { name: /test connection/i })).toBeInTheDocument()
    })

    it('should show test connection button within mTLS section', async () => {
      render(<HostModal isOpen={true} onClose={mockOnClose} host={null} />)
      const user = await openAddForm()

      // Enable mTLS
      const mtlsToggle = screen.getByLabelText(/enable mtls/i)
      await user.click(mtlsToggle)

      // Should have Test Connection button in mTLS section
      await waitFor(() => {
        const testButtons = screen.getAllByRole('button', { name: /test connection/i })
        expect(testButtons.length).toBeGreaterThan(0)
      })
    })
  })
})
