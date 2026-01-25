/**
 * OIDC Hooks
 * React Query hooks for OIDC configuration and group mappings
 *
 * Group-Based Permissions Refactor (v2.4.0)
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { toast } from 'sonner'
import type {
  OIDCConfig,
  OIDCConfigUpdateRequest,
  OIDCDiscoveryResponse,
  OIDCGroupMapping,
  OIDCGroupMappingCreateRequest,
  OIDCGroupMappingUpdateRequest,
  OIDCStatus,
} from '@/types/oidc'

const QUERY_KEYS = {
  config: ['oidc', 'config'],
  status: ['oidc', 'status'],
  groupMappings: ['oidc', 'group-mappings'],
}

// ==================== OIDC Status (Public) ====================

export function useOIDCStatus() {
  return useQuery<OIDCStatus>({
    queryKey: QUERY_KEYS.status,
    queryFn: async () => {
      return apiClient.get('/v2/oidc/status')
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

// ==================== OIDC Configuration (Admin) ====================

export function useOIDCConfig() {
  return useQuery<OIDCConfig>({
    queryKey: QUERY_KEYS.config,
    queryFn: async () => {
      return apiClient.get('/v2/oidc/config')
    },
  })
}

export function useUpdateOIDCConfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data: OIDCConfigUpdateRequest) => {
      return apiClient.put<OIDCConfig>('/v2/oidc/config', data)
    },
    onSuccess: (data) => {
      queryClient.setQueryData(QUERY_KEYS.config, data)
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.status })
      toast.success('Configuration saved', {
        description: 'OIDC settings have been updated.',
      })
    },
    onError: (error: Error) => {
      toast.error('Failed to save', {
        description: error.message,
      })
    },
  })
}

export function useDiscoverOIDC() {
  return useMutation({
    mutationFn: async () => {
      return apiClient.post<OIDCDiscoveryResponse>('/v2/oidc/discover', {})
    },
    onError: (error: Error) => {
      toast.error('Discovery failed', {
        description: error.message,
      })
    },
  })
}

// ==================== OIDC Group Mappings (Admin) ====================

export function useOIDCGroupMappings() {
  return useQuery<OIDCGroupMapping[]>({
    queryKey: QUERY_KEYS.groupMappings,
    queryFn: async () => {
      return apiClient.get('/v2/oidc/group-mappings')
    },
  })
}

export function useCreateOIDCGroupMapping() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data: OIDCGroupMappingCreateRequest) => {
      return apiClient.post<OIDCGroupMapping>('/v2/oidc/group-mappings', data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.groupMappings })
      toast.success('Mapping created', {
        description: 'OIDC group mapping has been created.',
      })
    },
    onError: (error: Error) => {
      toast.error('Failed to create mapping', {
        description: error.message,
      })
    },
  })
}

export function useUpdateOIDCGroupMapping() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, data }: { id: number; data: OIDCGroupMappingUpdateRequest }) => {
      return apiClient.put<OIDCGroupMapping>(`/v2/oidc/group-mappings/${id}`, data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.groupMappings })
      toast.success('Mapping updated', {
        description: 'OIDC group mapping has been updated.',
      })
    },
    onError: (error: Error) => {
      toast.error('Failed to update mapping', {
        description: error.message,
      })
    },
  })
}

export function useDeleteOIDCGroupMapping() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id: number) => {
      return apiClient.delete(`/v2/oidc/group-mappings/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.groupMappings })
      toast.success('Mapping deleted', {
        description: 'OIDC group mapping has been deleted.',
      })
    },
    onError: (error: Error) => {
      toast.error('Failed to delete mapping', {
        description: error.message,
      })
    },
  })
}

// ==================== Legacy Aliases (for backward compatibility) ====================

/** @deprecated Use useOIDCGroupMappings instead */
export const useOIDCRoleMappings = useOIDCGroupMappings
/** @deprecated Use useCreateOIDCGroupMapping instead */
export const useCreateOIDCRoleMapping = useCreateOIDCGroupMapping
/** @deprecated Use useUpdateOIDCGroupMapping instead */
export const useUpdateOIDCRoleMapping = useUpdateOIDCGroupMapping
/** @deprecated Use useDeleteOIDCGroupMapping instead */
export const useDeleteOIDCRoleMapping = useDeleteOIDCGroupMapping
