/**
 * OIDC Hooks
 * React Query hooks for OIDC configuration and role mappings
 *
 * Phase 4 of Multi-User Support (v2.3.0)
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { toast } from 'sonner'
import type {
  OIDCConfig,
  OIDCConfigUpdateRequest,
  OIDCDiscoveryResponse,
  OIDCRoleMapping,
  OIDCRoleMappingCreateRequest,
  OIDCRoleMappingUpdateRequest,
  OIDCStatus,
} from '@/types/oidc'

const QUERY_KEYS = {
  config: ['oidc', 'config'],
  status: ['oidc', 'status'],
  roleMappings: ['oidc', 'role-mappings'],
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

// ==================== OIDC Role Mappings (Admin) ====================

export function useOIDCRoleMappings() {
  return useQuery<OIDCRoleMapping[]>({
    queryKey: QUERY_KEYS.roleMappings,
    queryFn: async () => {
      return apiClient.get('/v2/oidc/role-mappings')
    },
  })
}

export function useCreateOIDCRoleMapping() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (data: OIDCRoleMappingCreateRequest) => {
      return apiClient.post<OIDCRoleMapping>('/v2/oidc/role-mappings', data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.roleMappings })
      toast.success('Mapping created', {
        description: 'OIDC role mapping has been created.',
      })
    },
    onError: (error: Error) => {
      toast.error('Failed to create mapping', {
        description: error.message,
      })
    },
  })
}

export function useUpdateOIDCRoleMapping() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, data }: { id: number; data: OIDCRoleMappingUpdateRequest }) => {
      return apiClient.put<OIDCRoleMapping>(`/v2/oidc/role-mappings/${id}`, data)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.roleMappings })
      toast.success('Mapping updated', {
        description: 'OIDC role mapping has been updated.',
      })
    },
    onError: (error: Error) => {
      toast.error('Failed to update mapping', {
        description: error.message,
      })
    },
  })
}

export function useDeleteOIDCRoleMapping() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (id: number) => {
      return apiClient.delete(`/v2/oidc/role-mappings/${id}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.roleMappings })
      toast.success('Mapping deleted', {
        description: 'OIDC role mapping has been deleted.',
      })
    },
    onError: (error: Error) => {
      toast.error('Failed to delete mapping', {
        description: error.message,
      })
    },
  })
}
