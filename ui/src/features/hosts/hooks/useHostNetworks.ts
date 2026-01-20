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
import { batchDeleteWithConcurrency, showBulkDeleteToast } from '@/lib/utils/batch'
import { getErrorMessage } from '@/lib/utils/errors'
import { pluralize } from '@/lib/utils/formatting'
import type { DockerNetwork } from '@/types/api'

interface DeleteNetworkParams {
  hostId: string
  networkId: string
  networkName: string
  force?: boolean
}

interface DeleteNetworksParams {
  hostId: string
  networks: Array<{ id: string; name: string }>
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
    onMutate: async (variables) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['host-networks', variables.hostId] })

      // Snapshot previous value
      const previousNetworks = queryClient.getQueryData<DockerNetwork[]>(['host-networks', variables.hostId])

      // Optimistically remove deleted network from cache
      if (previousNetworks) {
        queryClient.setQueryData<DockerNetwork[]>(
          ['host-networks', variables.hostId],
          previousNetworks.filter(n => n.id !== variables.networkId)
        )
      }

      return { previousNetworks }
    },
    onSuccess: (data, variables) => {
      toast.success(data.message || `Network '${variables.networkName}' deleted`)
    },
    onError: (error: unknown, variables, context) => {
      // Rollback on error
      if (context?.previousNetworks) {
        queryClient.setQueryData(['host-networks', variables.hostId], context.previousNetworks)
      }
      toast.error(getErrorMessage(error, 'Failed to delete network'))
    },
    onSettled: (_data, _error, variables) => {
      // Refetch to sync with actual state
      queryClient.invalidateQueries({ queryKey: ['host-networks', variables.hostId] })
    },
  })
}

/**
 * Hook to prune unused networks from a host
 *
 * Note: Unlike delete operations, prune does NOT use optimistic updates because
 * Docker may not remove all unused networks. Instead, we update the cache with
 * the actual list of removed networks from the response.
 */
export function usePruneNetworks(hostId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => pruneNetworks(hostId),
    onSuccess: (data) => {
      // Update cache with actual removed networks from response
      if (data.networks_removed && data.networks_removed.length > 0) {
        const removedSet = new Set(data.networks_removed)
        const previousNetworks = queryClient.getQueryData<DockerNetwork[]>(['host-networks', hostId])
        if (previousNetworks) {
          queryClient.setQueryData<DockerNetwork[]>(
            ['host-networks', hostId],
            previousNetworks.filter(n => !removedSet.has(n.name))
          )
        }
      }

      if (data.removed_count > 0) {
        toast.success(`Pruned ${data.removed_count} unused ${pluralize(data.removed_count, 'network')}`)
      } else {
        toast.info('No unused networks to prune')
      }
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, 'Failed to prune networks'))
    },
    onSettled: () => {
      // Refetch to sync with actual state
      queryClient.invalidateQueries({ queryKey: ['host-networks', hostId] })
    },
  })
}

/**
 * Hook to delete multiple networks from a host (parallel with concurrency limit)
 */
export function useDeleteNetworks() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (params: DeleteNetworksParams) => {
      return batchDeleteWithConcurrency(
        params.networks,
        async (network) => {
          const url = `/hosts/${params.hostId}/networks/${network.id}${params.force ? '?force=true' : ''}`
          await apiClient.delete<DeleteNetworkResponse>(url)
          return network.id
        },
        (network) => network.id
      )
    },
    onMutate: async (variables) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['host-networks', variables.hostId] })

      // Snapshot previous value
      const previousNetworks = queryClient.getQueryData<DockerNetwork[]>(['host-networks', variables.hostId])

      // Optimistically remove deleted networks from cache
      if (previousNetworks) {
        const deletedIds = new Set(variables.networks.map(n => n.id))
        queryClient.setQueryData<DockerNetwork[]>(
          ['host-networks', variables.hostId],
          previousNetworks.filter(n => !deletedIds.has(n.id))
        )
      }

      return { previousNetworks }
    },
    onSuccess: (results) => {
      const successCount = results.filter(r => r.success).length
      const failCount = results.filter(r => !r.success).length
      showBulkDeleteToast(successCount, failCount, 'network')
    },
    onError: (error: unknown, variables, context) => {
      // Rollback on error
      if (context?.previousNetworks) {
        queryClient.setQueryData(['host-networks', variables.hostId], context.previousNetworks)
      }
      toast.error(getErrorMessage(error, 'Failed to delete networks'))
    },
    onSettled: (_data, _error, variables) => {
      // Refetch to sync with actual state
      queryClient.invalidateQueries({ queryKey: ['host-networks', variables.hostId] })
    },
  })
}
