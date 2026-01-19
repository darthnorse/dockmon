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
