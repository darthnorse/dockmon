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

interface AuthContextValue {
  user: { id: number; username: string; is_first_login?: boolean } | null
  isLoading: boolean
  isAuthenticated: boolean
  isFirstLogin: boolean
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
    onSuccess: () => {
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

  const value: AuthContextValue = {
    user: data?.user ?? null,
    isLoading: isLoading || loginMutation.isPending || logoutMutation.isPending,
    isAuthenticated: !isError && data?.user != null,
    isFirstLogin: data?.user?.is_first_login ?? false,
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
