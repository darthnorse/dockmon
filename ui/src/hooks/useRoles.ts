/**
 * useRoles Hook
 * Manages Role Permissions with React Query
 *
 * Phase 5 of Multi-User Support (v2.3.0)
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type {
  CapabilitiesResponse,
  RolePermissionsResponse,
  UpdatePermissionsRequest,
  UpdatePermissionsResponse,
  ResetPermissionsResponse,
  RoleType,
} from '@/types/roles'
import { toast } from 'sonner'

const ROLES_QUERY_KEY = ['roles']
const CAPABILITIES_QUERY_KEY = ['capabilities']

/**
 * Fetch all capabilities with metadata
 */
export function useCapabilities() {
  return useQuery({
    queryKey: CAPABILITIES_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<CapabilitiesResponse>('/v2/roles/capabilities')
      return response
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - capabilities rarely change
  })
}

/**
 * Fetch all role permissions (admin only)
 */
export function useRolePermissions() {
  return useQuery({
    queryKey: [...ROLES_QUERY_KEY, 'permissions'],
    queryFn: async () => {
      const response = await apiClient.get<RolePermissionsResponse>('/v2/roles/permissions')
      return response
    },
    staleTime: 30 * 1000, // 30 seconds
  })
}

/**
 * Fetch default role permissions (admin only)
 */
export function useDefaultPermissions() {
  return useQuery({
    queryKey: [...ROLES_QUERY_KEY, 'defaults'],
    queryFn: async () => {
      const response = await apiClient.get<RolePermissionsResponse>('/v2/roles/permissions/defaults')
      return response
    },
    staleTime: 5 * 60 * 1000, // 5 minutes - defaults don't change
  })
}

/**
 * Update role permissions (admin only)
 */
export function useUpdatePermissions() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: UpdatePermissionsRequest) => {
      const response = await apiClient.put<UpdatePermissionsResponse>('/v2/roles/permissions', request)
      return response
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ROLES_QUERY_KEY })
      toast.success(data.message || 'Permissions updated successfully')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to update permissions')
    },
  })
}

/**
 * Reset role permissions to defaults (admin only)
 */
export function useResetPermissions() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (role?: RoleType) => {
      const body = { role: role ?? null }
      const response = await apiClient.post<ResetPermissionsResponse>('/v2/roles/permissions/reset', body)
      return response
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ROLES_QUERY_KEY })
      toast.success(data.message || 'Permissions reset to defaults')
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to reset permissions')
    },
  })
}
