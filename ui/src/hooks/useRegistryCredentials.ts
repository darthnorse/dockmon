/**
 * React Query hooks for registry credentials management
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import type { RegistryCredential, RegistryCredentialCreate, RegistryCredentialUpdate } from '@/types/api'

/**
 * Fetch all registry credentials
 */
export function useRegistryCredentials() {
  return useQuery({
    queryKey: ['registry-credentials'],
    queryFn: () => apiClient.get<RegistryCredential[]>('/registry-credentials'),
  })
}

/**
 * Create new registry credential
 */
export function useCreateRegistryCredential() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: RegistryCredentialCreate) =>
      apiClient.post<RegistryCredential>('/registry-credentials', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['registry-credentials'] })
      toast.success('Registry credential created successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to create credential: ${error.message}`)
    },
  })
}

/**
 * Update existing registry credential
 */
export function useUpdateRegistryCredential() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: RegistryCredentialUpdate }) =>
      apiClient.put<RegistryCredential>(`/registry-credentials/${id}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['registry-credentials'] })
      toast.success('Registry credential updated successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to update credential: ${error.message}`)
    },
  })
}

/**
 * Delete registry credential
 */
export function useDeleteRegistryCredential() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: number) => apiClient.delete(`/registry-credentials/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['registry-credentials'] })
      toast.success('Registry credential deleted successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to delete credential: ${error.message}`)
    },
  })
}
