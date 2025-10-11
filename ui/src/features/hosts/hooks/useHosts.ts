/**
 * useHosts - TanStack Query hooks for host CRUD operations
 * Phase 3d Sub-Phase 6
 *
 * FEATURES:
 * - useHosts(): Fetch all hosts
 * - useAddHost(): POST /api/hosts
 * - useUpdateHost(): PUT /api/hosts/{id}
 * - useDeleteHost(): DELETE /api/hosts/{id}
 *
 * USAGE:
 * const { data: hosts, isLoading } = useHosts()
 * const addMutation = useAddHost()
 * addMutation.mutate(hostConfig)
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'

// Type for API errors from axios/fetch responses
interface ApiError extends Error {
  response?: {
    data?: {
      detail?: string
    }
  }
}

export interface Host {
  id: string
  name: string
  url: string
  status: string
  security_status?: string | null
  last_checked: string
  container_count: number
  error?: string | null
  tags?: string[]
  description?: string | null
  // Phase 5 - System information
  os_type?: string | null
  os_version?: string | null
  kernel_version?: string | null
  docker_version?: string | null
  daemon_started_at?: string | null
}

export interface HostConfig {
  name: string
  url: string
  tls_cert?: string | null
  tls_key?: string | null
  tls_ca?: string | null
  tags?: string[]
  description?: string | null
}

/**
 * Fetch all hosts
 */
async function fetchHosts(): Promise<Host[]> {
  return await apiClient.get<Host[]>('/hosts')
}

/**
 * Add a new host
 */
async function addHost(config: HostConfig): Promise<Host> {
  return await apiClient.post<Host>('/hosts', config)
}

/**
 * Update an existing host
 */
async function updateHost(id: string, config: HostConfig): Promise<Host> {
  return await apiClient.put<Host>(`/hosts/${id}`, config)
}

/**
 * Delete a host
 */
async function deleteHost(id: string): Promise<void> {
  await apiClient.delete(`/hosts/${id}`)
}

/**
 * Hook to fetch all hosts
 */
export function useHosts() {
  return useQuery({
    queryKey: ['hosts'],
    queryFn: fetchHosts,
    staleTime: 1000 * 30, // 30 seconds (hosts don't change often)
    refetchInterval: 1000 * 60, // Refetch every 60 seconds for status updates
  })
}

/**
 * Hook to add a new host
 */
export function useAddHost() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: addHost,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['hosts'] })
      queryClient.invalidateQueries({ queryKey: ['tags'] }) // Invalidate tags cache
      toast.success(`Host "${data.name}" added successfully`)
    },
    onError: (error: unknown) => {
      const apiError = error as ApiError
      const message = apiError.response?.data?.detail || apiError.message || 'Failed to add host'
      toast.error(message)
    },
  })
}

/**
 * Hook to update a host
 */
export function useUpdateHost() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, config }: { id: string; config: HostConfig }) => updateHost(id, config),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['hosts'] })
      queryClient.invalidateQueries({ queryKey: ['tags'] })
      toast.success(`Host "${data.name}" updated successfully`)
    },
    onError: (error: unknown) => {
      const apiError = error as ApiError
      const message = apiError.response?.data?.detail || apiError.message || 'Failed to update host'
      toast.error(message)
    },
  })
}

/**
 * Hook to delete a host
 */
export function useDeleteHost() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteHost,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hosts'] })
      queryClient.invalidateQueries({ queryKey: ['tags'] })
      toast.success('Host deleted successfully')
    },
    onError: (error: unknown) => {
      const apiError = error as ApiError
      const message = apiError.response?.data?.detail || apiError.message || 'Failed to delete host'
      toast.error(message)
    },
  })
}
