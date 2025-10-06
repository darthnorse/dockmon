/**
 * LoginPage Tests
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@/test/utils'
import { LoginPage } from './LoginPage'
import { AuthProvider } from './AuthContext'
import { ApiError } from '@/lib/api/client'
import { authApi } from './api'

// Mock the auth API
vi.mock('./api', () => ({
  authApi: {
    login: vi.fn(),
    logout: vi.fn(),
    getCurrentUser: vi.fn(),
  },
}))

describe('LoginPage', () => {
  let queryClient: QueryClient

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
      logger: {
        log: () => {},
        warn: () => {},
        error: () => {},
      },
    })

    vi.clearAllMocks()
    // Default: not authenticated
    vi.mocked(authApi.getCurrentUser).mockRejectedValue(
      new Error('Unauthorized')
    )
  })

  const renderLoginPage = () => {
    return render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </QueryClientProvider>
    )
  }

  describe('rendering', () => {
    it('should render login form', () => {
      renderLoginPage()

      expect(screen.getByRole('heading', { name: /dockmon/i })).toBeInTheDocument()
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /log in/i })).toBeInTheDocument()
    })

    it('should show default credentials hint', () => {
      renderLoginPage()

      expect(screen.getByText(/default credentials/i)).toBeInTheDocument()
      expect(screen.getByText(/admin/)).toBeInTheDocument()
      expect(screen.getByText(/dockmon123/)).toBeInTheDocument()
    })

    it('should focus username field on mount', () => {
      renderLoginPage()

      const usernameInput = screen.getByLabelText(/username/i)
      expect(usernameInput).toHaveFocus()
    })
  })

  describe('form validation', () => {
    it('should show error when submitting empty form', async () => {
      const user = userEvent.setup()
      renderLoginPage()

      const submitButton = screen.getByRole('button', { name: /log in/i })
      await user.click(submitButton)

      expect(
        await screen.findByText(/please enter both username and password/i)
      ).toBeInTheDocument()
    })

    it('should trim whitespace from username', async () => {
      const user = userEvent.setup()
      vi.mocked(authApi.login).mockResolvedValueOnce({
        user: { id: 1, username: 'testuser', is_first_login: false },
        message: 'Login successful',
      })
      vi.mocked(authApi.getCurrentUser).mockResolvedValueOnce({
        user: { id: 1, username: 'testuser' },
      })

      renderLoginPage()

      await user.type(screen.getByLabelText(/username/i), '  testuser  ')
      await user.type(screen.getByLabelText(/password/i), 'password')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      await waitFor(() => {
        expect(authApi.login).toHaveBeenCalledWith({
          username: 'testuser', // Trimmed
          password: 'password',
        })
      })
    })
  })

  describe('login flow', () => {
    it('should login successfully with valid credentials', async () => {
      const user = userEvent.setup()
      vi.mocked(authApi.login).mockResolvedValueOnce({
        user: { id: 1, username: 'admin', is_first_login: false },
        message: 'Login successful',
      })
      vi.mocked(authApi.getCurrentUser).mockResolvedValueOnce({
        user: { id: 1, username: 'admin' },
      })

      renderLoginPage()

      await user.type(screen.getByLabelText(/username/i), 'admin')
      await user.type(screen.getByLabelText(/password/i), 'dockmon123')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      await waitFor(() => {
        expect(authApi.login).toHaveBeenCalledWith({
          username: 'admin',
          password: 'dockmon123',
        })
      })
    })

    it('should show loading state during login', async () => {
      const user = userEvent.setup()
      vi.mocked(authApi.login).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      renderLoginPage()

      await user.type(screen.getByLabelText(/username/i), 'admin')
      await user.type(screen.getByLabelText(/password/i), 'pass')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /logging in/i })).toBeDisabled()
      })
    })

    it('should disable form during login', async () => {
      const user = userEvent.setup()
      vi.mocked(authApi.login).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      renderLoginPage()

      await user.type(screen.getByLabelText(/username/i), 'admin')
      await user.type(screen.getByLabelText(/password/i), 'pass')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      await waitFor(() => {
        expect(screen.getByLabelText(/username/i)).toBeDisabled()
        expect(screen.getByLabelText(/password/i)).toBeDisabled()
      })
    })
  })

  describe('error handling', () => {
    it('should show error for 401 Unauthorized', async () => {
      const user = userEvent.setup()
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new ApiError('Unauthorized', 401, { detail: 'Invalid credentials' })
      )

      renderLoginPage()

      await user.type(screen.getByLabelText(/username/i), 'wrong')
      await user.type(screen.getByLabelText(/password/i), 'wrong')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      expect(
        await screen.findByText(/invalid username or password/i)
      ).toBeInTheDocument()
    })

    it('should show error for 429 Rate Limit', async () => {
      const user = userEvent.setup()
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new ApiError('Too Many Requests', 429)
      )

      renderLoginPage()

      await user.type(screen.getByLabelText(/username/i), 'admin')
      await user.type(screen.getByLabelText(/password/i), 'pass')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      expect(
        await screen.findByText(/too many login attempts/i)
      ).toBeInTheDocument()
    })

    it('should show generic error for other API errors', async () => {
      const user = userEvent.setup()
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new ApiError('Internal Server Error', 500)
      )

      renderLoginPage()

      await user.type(screen.getByLabelText(/username/i), 'admin')
      await user.type(screen.getByLabelText(/password/i), 'pass')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      expect(
        await screen.findByText(/login failed. please try again/i)
      ).toBeInTheDocument()
    })

    it('should show connection error for network errors', async () => {
      const user = userEvent.setup()
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new Error('Network error')
      )

      renderLoginPage()

      await user.type(screen.getByLabelText(/username/i), 'admin')
      await user.type(screen.getByLabelText(/password/i), 'pass')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      expect(
        await screen.findByText(/connection error/i)
      ).toBeInTheDocument()
    })

    it('should clear error when user starts typing again', async () => {
      const user = userEvent.setup()
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new ApiError('Unauthorized', 401)
      )

      renderLoginPage()

      await user.type(screen.getByLabelText(/username/i), 'wrong')
      await user.type(screen.getByLabelText(/password/i), 'wrong')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      // Error should appear
      expect(
        await screen.findByText(/invalid username or password/i)
      ).toBeInTheDocument()

      // Clear and start typing again
      const usernameInput = screen.getByLabelText(/username/i)
      await user.clear(usernameInput)
      await user.type(usernameInput, 'a')

      // Submit again to trigger new validation
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new ApiError('Unauthorized', 401)
      )
      await user.type(screen.getByLabelText(/password/i), 'b')
      await user.click(screen.getByRole('button', { name: /log in/i }))

      // Error should reappear (proving it was cleared)
      expect(
        await screen.findByText(/invalid username or password/i)
      ).toBeInTheDocument()
    })
  })

  describe('accessibility', () => {
    it('should have proper form labels', () => {
      renderLoginPage()

      expect(screen.getByLabelText(/username/i)).toHaveAttribute(
        'id',
        'username'
      )
      expect(screen.getByLabelText(/password/i)).toHaveAttribute(
        'id',
        'password'
      )
    })

    it('should have autocomplete attributes', () => {
      renderLoginPage()

      expect(screen.getByLabelText(/username/i)).toHaveAttribute(
        'autocomplete',
        'username'
      )
      expect(screen.getByLabelText(/password/i)).toHaveAttribute(
        'autocomplete',
        'current-password'
      )
    })

    it('should mark error as alert for screen readers', async () => {
      const user = userEvent.setup()
      renderLoginPage()

      await user.click(screen.getByRole('button', { name: /log in/i }))

      const errorAlert = await screen.findByRole('alert')
      expect(errorAlert).toHaveTextContent(/please enter both username and password/i)
    })
  })
})
