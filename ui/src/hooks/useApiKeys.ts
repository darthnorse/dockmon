/**
 * useApiKeys Hook
 * Manages API key CRUD operations with React Query
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import {
  ApiKey,
  CreateApiKeyRequest,
  CreateApiKeyResponse,
  UpdateApiKeyRequest,
} from '@/types/api-keys'
import { toast } from 'sonner'

const API_KEYS_QUERY_KEY = ['api-keys']

/**
 * Fetch all API keys for current user
 */
export function useApiKeys() {
  return useQuery({
    queryKey: API_KEYS_QUERY_KEY,
    queryFn: async () => {
      const response = await apiClient.get<ApiKey[]>('/v2/api-keys/')
      return response || []
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

/**
 * Create a new API key
 */
export function useCreateApiKey() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateApiKeyRequest) => {
      const response = await apiClient.post<CreateApiKeyResponse>('/v2/api-keys/', request)
      return response
    },
    onSuccess: () => {
      // Invalidate list but DON'T refetch immediately
      // User needs to copy the key first
      queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY })
    },
    onError: (error) => {
      console.error('Failed to create API key:', error)
    },
  })
}

/**
 * Update an existing API key (name, description, scopes, IP allowlist)
 */
export function useUpdateApiKey() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ keyId, data }: { keyId: number; data: UpdateApiKeyRequest }) => {
      const response = await apiClient.patch<ApiKey>(`/v2/api-keys/${keyId}`, data)
      return response
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY })
      toast.success('API key updated successfully')
    },
    onError: (error) => {
      toast.error('Failed to update API key')
      console.error('Failed to update API key:', error)
    },
  })
}

/**
 * Revoke an API key (soft delete - keeps audit trail)
 */
export function useRevokeApiKey() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (keyId: number) => {
      await apiClient.delete<{ message: string }>(`/v2/api-keys/${keyId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY })
      toast.success('API key revoked successfully')
    },
    onError: (error) => {
      toast.error('Failed to revoke API key')
      console.error('Failed to revoke API key:', error)
    },
  })
}

/**
 * Refresh API keys list
 */
export function useRefreshApiKeys() {
  const queryClient = useQueryClient()

  return {
    refetch: () => queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY }),
  }
}
