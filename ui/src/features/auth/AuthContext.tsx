/**
 * Authentication Context
 *
 * SECURITY:
 * - Cookie-based authentication (HttpOnly, Secure, SameSite=strict)
 * - No tokens stored in localStorage/sessionStorage
 * - Automatic session validation on mount
 *
 * PATTERN:
 * - Uses TanStack Query for server state
 * - Context only for auth status and actions
 * - No global state management needed
 */

import { createContext, useContext, type ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authApi } from './api'
import type { LoginRequest } from '@/types/api'

interface AuthUserGroup {
  id: number
  name: string
}

interface AuthUser {
  id: number
  username: string
  display_name?: string | null
  is_first_login?: boolean
  must_change_password?: boolean
  groups: AuthUserGroup[]
}

interface AuthContextValue {
  user: AuthUser | null
  capabilities: string[]
  isLoading: boolean
  isAuthenticated: boolean
  isFirstLogin: boolean
  mustChangePassword: boolean
  isAdmin: boolean
  hasCapability: (capability: string) => boolean
  login: (credentials: LoginRequest) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  // Query current user (validates session cookie)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['auth', 'currentUser'],
    queryFn: authApi.getCurrentUser,
    retry: false, // Don't retry on 401
    staleTime: 5 * 60 * 1000, // 5 minutes
  })

  // Login mutation
  const loginMutation = useMutation({
    mutationFn: authApi.login,
    onSuccess: (response, variables) => {
      // If first login, temporarily store password for password change modal
      if (response.user.is_first_login) {
        sessionStorage.setItem('_tmp_pwd', variables.password)
      }
      // Invalidate current user query to refetch
      void queryClient.invalidateQueries({ queryKey: ['auth', 'currentUser'] })
    },
  })

  // Logout mutation
  const logoutMutation = useMutation({
    mutationFn: authApi.logout,
    onSuccess: () => {
      // Clear all queries on logout
      queryClient.clear()
    },
  })

  // Extract capabilities from response
  const capabilities = data?.capabilities ?? []

  // Check if user is admin (in Administrators group or has users.manage capability)
  const isAdmin =
    data?.user?.groups?.some((g) => g.name === 'Administrators') ??
    capabilities.includes('users.manage') ??
    false

  // Helper to check if user has a specific capability
  const hasCapability = (capability: string): boolean => {
    return capabilities.includes(capability)
  }

  const value: AuthContextValue = {
    user: data?.user ?? null,
    capabilities,
    isLoading: isLoading || loginMutation.isPending || logoutMutation.isPending,
    isAuthenticated: !isError && data?.user != null,
    isFirstLogin: data?.user?.is_first_login ?? false,
    mustChangePassword: data?.user?.must_change_password ?? false,
    isAdmin,
    hasCapability,
    login: async (credentials) => {
      await loginMutation.mutateAsync(credentials)
    },
    logout: async () => {
      await logoutMutation.mutateAsync()
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

/**
 * Hook to access auth context
 * Throws if used outside AuthProvider
 */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
