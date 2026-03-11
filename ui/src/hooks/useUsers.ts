/**
 * useUsers Hook
 * Manages User CRUD operations with React Query
 *
 * Phase 3 of Multi-User Support (v2.3.0)
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/features/auth/AuthContext'
import { apiClient } from '@/lib/api/client'
import type {
  User,
  UserListResponse,
  CreateUserRequest,
  UpdateUserRequest,
  ResetPasswordRequest,
  ResetPasswordResponse,
  DeleteUserResponse,
} from '@/types/users'
import { toast } from 'sonner'

const USERS_QUERY_KEY = ['users']
const PENDING_COUNT_QUERY_KEY = ['users', 'pending-count']

/**
 * Fetch all users (admin only)
 */
export function useUsers() {
  return useQuery({
    queryKey: USERS_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<UserListResponse>('/v2/users')
      return response
    },
    staleTime: 30 * 1000, // 30 seconds
  })
}

/**
 * Get a single user by ID (admin only)
 */
export function useUser(userId: number | null) {
  return useQuery({
    queryKey: [...USERS_QUERY_KEY, userId],
    queryFn: async () => {
      if (userId === null) return null
      const response = await apiClient.get<User>(`/v2/users/${userId}`)
      return response
    },
    enabled: userId !== null,
    staleTime: 30 * 1000,
  })
}

/**
 * Create a new user (admin only)
 */
export function useCreateUser() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateUserRequest) => {
      const response = await apiClient.post<User>('/v2/users', request)
      return response
    },
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      toast.success(`User "${user.username}" created successfully`)
    },
    onError: (error: Error) => {
      console.error('Failed to create user:', error)
      toast.error('Failed to create user. Please try again.')
    },
  })
}

/**
 * Update an existing user (admin only)
 */
export function useUpdateUser() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ userId, data }: { userId: number; data: UpdateUserRequest }) => {
      const response = await apiClient.put<User>(`/v2/users/${userId}`, data)
      return response
    },
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      toast.success(`User "${user.username}" updated successfully`)
    },
    onError: (error: Error) => {
      console.error('Failed to update user:', error)
      toast.error('Failed to update user. Please try again.')
    },
  })
}

/**
 * Delete a user (admin only)
 */
export function useDeleteUser() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (userId: number) => {
      const response = await apiClient.delete<DeleteUserResponse>(`/v2/users/${userId}`)
      return response
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      queryClient.invalidateQueries({ queryKey: ['groups'] })
      toast.success(response.message || 'User deleted successfully')
    },
    onError: (error: Error) => {
      console.error('Failed to delete user:', error)
      toast.error('Failed to delete user. Please try again.')
    },
  })
}

/**
 * Reset a user's password (admin only)
 */
export function useResetUserPassword() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      userId,
      data,
    }: {
      userId: number
      data?: ResetPasswordRequest
    }) => {
      const response = await apiClient.post<ResetPasswordResponse>(
        `/v2/users/${userId}/reset-password`,
        data || {}
      )
      return response
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      if (response.temporary_password) {
        toast.info('Temporary password generated - copy it now')
      } else {
        toast.success(response.message || 'Password reset successfully')
      }
    },
    onError: (error: Error) => {
      console.error('Failed to reset password:', error)
      toast.error('Failed to reset password. Please try again.')
    },
  })
}

/**
 * Fetch count of users pending approval (admin only)
 */
export function usePendingUserCount() {
  const { hasCapability } = useAuth()
  return useQuery({
    queryKey: PENDING_COUNT_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<{ count: number }>('/v2/users/pending-count')
      return response
    },
    enabled: hasCapability('users.manage'),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000, // Poll every minute for new pending users
  })
}

/**
 * Approve a single user
 */
export function useApproveUser() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (userId: number) => {
      const response = await apiClient.post<{ message: string }>(`/v2/users/${userId}/approve`)
      return response
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      queryClient.invalidateQueries({ queryKey: PENDING_COUNT_QUERY_KEY })
      toast.success(response.message)
    },
    onError: () => {
      toast.error('Failed to approve user')
    },
  })
}

/**
 * Approve all pending users
 */
export function useApproveAllUsers() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => {
      const response = await apiClient.post<{ message: string; count: number }>('/v2/users/approve-all')
      return response
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      queryClient.invalidateQueries({ queryKey: PENDING_COUNT_QUERY_KEY })
      toast.success(response.message)
    },
    onError: () => {
      toast.error('Failed to approve users')
    },
  })
}
