/**
 * useRoles Hook
 * Manages capabilities and legacy role permissions with React Query
 *
 * Group-Based Permissions Refactor (v2.4.0)
 *
 * Note: Role permission hooks are deprecated. Use useGroups.ts for group permissions instead.
 * Only useCapabilities is still actively used (for the permission matrix).
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
 * This is still used by the group permissions UI
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

// ==================== Legacy Hooks (Deprecated) ====================

/**
 * @deprecated Use useGroupPermissions from useGroups.ts instead
 */
export function useRolePermissions() {
  return useQuery({
    queryKey: [...ROLES_QUERY_KEY, 'permissions'],
    queryFn: async () => {
      const response = await apiClient.get<RolePermissionsResponse>('/v2/roles/permissions')
      return response
    },
    staleTime: 30 * 1000,
  })
}

/**
 * @deprecated Role defaults no longer used - groups have their own permissions
 */
export function useDefaultPermissions() {
  return useQuery({
    queryKey: [...ROLES_QUERY_KEY, 'defaults'],
    queryFn: async () => {
      const response = await apiClient.get<RolePermissionsResponse>('/v2/roles/permissions/defaults')
      return response
    },
    staleTime: 5 * 60 * 1000,
  })
}

/**
 * @deprecated Use useUpdateGroupPermissions from useGroups.ts instead
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
 * @deprecated Role resets no longer used - groups have their own permissions
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
