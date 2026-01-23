/**
 * useUsers Hook
 * Manages User CRUD operations with React Query
 *
 * Phase 3 of Multi-User Support (v2.3.0)
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
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

/**
 * Fetch all users (admin only)
 */
export function useUsers(includeDeleted = false) {
  return useQuery({
    queryKey: [...USERS_QUERY_KEY, { includeDeleted }],
    queryFn: async () => {
      const params = includeDeleted ? { include_deleted: 'true' } : {}
      const response = await apiClient.get<UserListResponse>('/v2/users', { params })
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
      toast.error(error.message || 'Failed to create user')
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
      toast.error(error.message || 'Failed to update user')
    },
  })
}

/**
 * Soft delete a user (admin only)
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
      toast.success(response.message || 'User deactivated successfully')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to deactivate user')
    },
  })
}

/**
 * Reactivate a soft-deleted user (admin only)
 */
export function useReactivateUser() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (userId: number) => {
      const response = await apiClient.post<User>(`/v2/users/${userId}/reactivate`)
      return response
    },
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      toast.success(`User "${user.username}" reactivated successfully`)
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to reactivate user')
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
      toast.error(error.message || 'Failed to reset password')
    },
  })
}
