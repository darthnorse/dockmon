/**
 * useHostNetworks - TanStack Query hooks for host networks
 *
 * FEATURES:
 * - useHostNetworks(): Fetch all networks for a host
 * - useDeleteNetwork(): Delete a network from a host
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { getErrorMessage } from '@/lib/utils/errors'
import type { DockerNetwork } from '@/types/api'

interface DeleteNetworkParams {
  hostId: string
  networkId: string
  networkName: string
  force?: boolean
}

interface DeleteNetworkResponse {
  success: boolean
  message: string
}

interface PruneNetworksResponse {
  removed_count: number
  networks_removed: string[]
}

/**
 * Fetch all networks for a host
 */
async function fetchHostNetworks(hostId: string): Promise<DockerNetwork[]> {
  return await apiClient.get<DockerNetwork[]>(`/hosts/${hostId}/networks`)
}

/**
 * Delete a network from a host
 */
async function deleteNetwork(params: DeleteNetworkParams): Promise<DeleteNetworkResponse> {
  const url = `/hosts/${params.hostId}/networks/${params.networkId}${params.force ? '?force=true' : ''}`
  return await apiClient.delete<DeleteNetworkResponse>(url)
}

/**
 * Prune unused networks from a host
 */
async function pruneNetworks(hostId: string): Promise<PruneNetworksResponse> {
  return await apiClient.post<PruneNetworksResponse>(`/hosts/${hostId}/networks/prune`)
}

/**
 * Hook to fetch networks for a specific host
 */
export function useHostNetworks(hostId: string) {
  return useQuery({
    queryKey: ['host-networks', hostId],
    queryFn: () => fetchHostNetworks(hostId),
    enabled: !!hostId,
    staleTime: 30_000, // 30 seconds
  })
}

/**
 * Hook to delete a network from a host
 */
export function useDeleteNetwork() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteNetwork,
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['host-networks', variables.hostId] })
      toast.success(data.message || `Network '${variables.networkName}' deleted`)
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, 'Failed to delete network'))
    },
  })
}

/**
 * Hook to prune unused networks from a host
 */
export function usePruneNetworks(hostId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => pruneNetworks(hostId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['host-networks', hostId] })
      if (data.removed_count > 0) {
        toast.success(`Pruned ${data.removed_count} unused network${data.removed_count === 1 ? '' : 's'}`)
      } else {
        toast.info('No unused networks to prune')
      }
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, 'Failed to prune networks'))
    },
  })
}
