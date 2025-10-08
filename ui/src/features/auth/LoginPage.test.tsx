/**
 * LoginPage Tests
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
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

  // Helper to fill form fields reliably
  const fillLoginForm = async (username: string, password: string) => {
    const usernameInput = await screen.findByLabelText(/username/i)
    const passwordInput = await screen.findByLabelText(/password/i)

    fireEvent.change(usernameInput, { target: { value: username } })
    fireEvent.change(passwordInput, { target: { value: password } })

    return { usernameInput, passwordInput }
  }

  describe('rendering', () => {
    it('should render login form', async () => {
      renderLoginPage()

      // Wait for auth check to complete
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /dockmon/i })).toBeInTheDocument()
      })

      expect(await screen.findByLabelText(/username/i)).toBeInTheDocument()
      expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
      expect(await screen.findByRole('button', { name: /log in/i })).toBeInTheDocument()
    })

    it('should show default credentials hint', async () => {
      renderLoginPage()

      await waitFor(() => {
        expect(screen.getByText(/default credentials/i)).toBeInTheDocument()
      })

      expect(screen.getByText(/admin/)).toBeInTheDocument()
      expect(screen.getByText(/test1234/)).toBeInTheDocument()
    })

    // Skip: jsdom doesn't properly handle autoFocus attribute
    it.skip('should focus username field on mount', async () => {
      renderLoginPage()

      const usernameInput = await screen.findByLabelText(/username/i)

      // Wait for auth check to complete (input becomes enabled)
      await waitFor(() => {
        expect(usernameInput).not.toBeDisabled()
      })

      expect(usernameInput).toHaveFocus()
    })
  })

  describe('form validation', () => {
    it('should show error when submitting empty form', async () => {
      const user = userEvent.setup()
      renderLoginPage()

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      await user.click(submitButton)

      expect(
        await screen.findByText(/please enter both username and password/i)
      ).toBeInTheDocument()
    })

    it('should trim whitespace from username', async () => {
      vi.mocked(authApi.login).mockResolvedValueOnce({
        user: { id: 1, username: 'testuser', is_first_login: false },
        message: 'Login successful',
      })
      // Mock getCurrentUser to be called twice: initial check + refetch after login
      vi.mocked(authApi.getCurrentUser)
        .mockRejectedValueOnce(new Error('Unauthorized'))
        .mockResolvedValueOnce({
          user: { id: 1, username: 'testuser' },
        })

      renderLoginPage()

      await fillLoginForm('  testuser  ', 'password')

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      fireEvent.click(submitButton)

      await waitFor(() => {
        expect(authApi.login).toHaveBeenCalled()
      })
      expect(vi.mocked(authApi.login).mock.calls[0]?.[0]).toEqual({
        username: 'testuser', // Trimmed
        password: 'password',
      })
    })
  })

  describe('login flow', () => {
    it('should login successfully with valid credentials', async () => {
      vi.mocked(authApi.login).mockResolvedValueOnce({
        user: { id: 1, username: 'admin', is_first_login: false },
        message: 'Login successful',
      })
      // Mock getCurrentUser to be called twice: initial check + refetch after login
      vi.mocked(authApi.getCurrentUser)
        .mockRejectedValueOnce(new Error('Unauthorized'))
        .mockResolvedValueOnce({
          user: { id: 1, username: 'admin' },
        })

      renderLoginPage()

      await fillLoginForm('admin', 'dockmon123')

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      fireEvent.click(submitButton)

      await waitFor(() => {
        expect(authApi.login).toHaveBeenCalled()
      })
      expect(vi.mocked(authApi.login).mock.calls[0]?.[0]).toEqual({
        username: 'admin',
        password: 'dockmon123',
      })
    })

    it('should show loading state during login', async () => {
      vi.mocked(authApi.login).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      renderLoginPage()

      await fillLoginForm('admin', 'pass')

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      fireEvent.click(submitButton)

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /logging in/i })).toBeDisabled()
      })
    })

    it('should disable form during login', async () => {
      vi.mocked(authApi.login).mockImplementation(
        () => new Promise(() => {}) // Never resolves
      )

      renderLoginPage()

      await fillLoginForm('admin', 'pass')

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      fireEvent.click(submitButton)

      await waitFor(() => {
        expect(screen.getByLabelText(/username/i)).toBeDisabled()
        expect(screen.getByLabelText(/password/i)).toBeDisabled()
      })
    })
  })

  describe('error handling', () => {
    it('should show error for 401 Unauthorized', async () => {
      vi.mocked(authApi.login).mockImplementation(() => {
        return Promise.reject(new ApiError('Unauthorized', 401, { detail: 'Invalid credentials' }))
      })

      renderLoginPage()

      await fillLoginForm('wrong', 'wrong')

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      fireEvent.click(submitButton)

      expect(
        await screen.findByText(/invalid username or password/i)
      ).toBeInTheDocument()
    })

    it('should show error for 429 Rate Limit', async () => {
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new ApiError('Too Many Requests', 429)
      )

      renderLoginPage()

      await fillLoginForm('admin', 'pass')

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      fireEvent.click(submitButton)

      expect(
        await screen.findByText(/too many login attempts/i)
      ).toBeInTheDocument()
    })

    it('should show generic error for other API errors', async () => {
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new ApiError('Internal Server Error', 500)
      )

      renderLoginPage()

      await fillLoginForm('admin', 'pass')

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      fireEvent.click(submitButton)

      expect(
        await screen.findByText(/login failed. please try again/i)
      ).toBeInTheDocument()
    })

    it('should show connection error for network errors', async () => {
      vi.mocked(authApi.login).mockRejectedValueOnce(
        new Error('Network error')
      )

      renderLoginPage()

      await fillLoginForm('admin', 'pass')

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      fireEvent.click(submitButton)

      expect(
        await screen.findByText(/connection error/i)
      ).toBeInTheDocument()
    })

    it('should clear error when user starts typing again', async () => {
      vi.mocked(authApi.login).mockRejectedValue(
        new ApiError('Unauthorized', 401)
      )

      renderLoginPage()

      await fillLoginForm('wrong', 'wrong')

      const submitButton = await screen.findByRole('button', { name: /log in/i })
      fireEvent.click(submitButton)

      // Error should appear
      expect(
        await screen.findByText(/invalid username or password/i)
      ).toBeInTheDocument()

      // Type in username field (should clear error)
      const usernameInput = await screen.findByLabelText(/username/i)
      fireEvent.change(usernameInput, { target: { value: 'new' } })

      // Error should be cleared (not visible anymore)
      expect(
        screen.queryByText(/invalid username or password/i)
      ).not.toBeInTheDocument()
    })
  })

  describe('accessibility', () => {
    it('should have proper form labels', async () => {
      renderLoginPage()

      expect(await screen.findByLabelText(/username/i)).toHaveAttribute(
        'id',
        'username'
      )
      expect(screen.getByLabelText(/password/i)).toHaveAttribute(
        'id',
        'password'
      )
    })

    it('should have autocomplete attributes', async () => {
      renderLoginPage()

      expect(await screen.findByLabelText(/username/i)).toHaveAttribute(
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

      await user.click(await screen.findByRole('button', { name: /log in/i }))

      const errorAlert = await screen.findByRole('alert')
      expect(errorAlert).toHaveTextContent(/please enter both username and password/i)
    })
  })
})
