/**
 * useHostVolumes - TanStack Query hooks for host volumes
 *
 * FEATURES:
 * - useHostVolumes(): Fetch all volumes for a host
 * - useDeleteVolume(): Delete a volume from a host
 * - useDeleteVolumes(): Bulk delete volumes
 * - usePruneVolumes(): Prune unused volumes
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { batchDeleteWithConcurrency, showBulkDeleteToast } from '@/lib/utils/batch'
import { getErrorMessage } from '@/lib/utils/errors'
import { pluralize, formatBytes } from '@/lib/utils/formatting'
import type { DockerVolume } from '@/types/api'

interface DeleteVolumeParams {
  hostId: string
  volumeName: string
  force?: boolean
}

interface DeleteVolumesParams {
  hostId: string
  volumes: Array<{ name: string }>
  force?: boolean
}

interface DeleteVolumeResponse {
  success: boolean
  message: string
}

interface PruneVolumesResponse {
  removed_count: number
  space_reclaimed: number
  volumes_removed: string[]
}

/**
 * Fetch all volumes for a host
 */
async function fetchHostVolumes(hostId: string): Promise<DockerVolume[]> {
  return await apiClient.get<DockerVolume[]>(`/hosts/${hostId}/volumes`)
}

/**
 * Delete a volume from a host
 */
async function deleteVolume(params: DeleteVolumeParams): Promise<DeleteVolumeResponse> {
  const url = `/hosts/${params.hostId}/volumes/${encodeURIComponent(params.volumeName)}${params.force ? '?force=true' : ''}`
  return await apiClient.delete<DeleteVolumeResponse>(url)
}

/**
 * Prune unused volumes from a host
 */
async function pruneVolumes(hostId: string): Promise<PruneVolumesResponse> {
  return await apiClient.post<PruneVolumesResponse>(`/hosts/${hostId}/volumes/prune`)
}

/**
 * Hook to fetch volumes for a specific host
 */
export function useHostVolumes(hostId: string) {
  return useQuery({
    queryKey: ['host-volumes', hostId],
    queryFn: () => fetchHostVolumes(hostId),
    enabled: !!hostId,
    staleTime: 30_000, // 30 seconds
  })
}

/**
 * Hook to delete a volume from a host
 */
export function useDeleteVolume() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteVolume,
    onMutate: async (variables) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['host-volumes', variables.hostId] })

      // Snapshot previous value
      const previousVolumes = queryClient.getQueryData<DockerVolume[]>(['host-volumes', variables.hostId])

      // Optimistically remove deleted volume from cache
      if (previousVolumes) {
        queryClient.setQueryData<DockerVolume[]>(
          ['host-volumes', variables.hostId],
          previousVolumes.filter(v => v.name !== variables.volumeName)
        )
      }

      return { previousVolumes }
    },
    onSuccess: (data, variables) => {
      toast.success(data.message || `Volume '${variables.volumeName}' deleted`)
    },
    onError: (error: unknown, variables, context) => {
      // Rollback on error
      if (context?.previousVolumes) {
        queryClient.setQueryData(['host-volumes', variables.hostId], context.previousVolumes)
      }
      toast.error(getErrorMessage(error, 'Failed to delete volume'))
    },
    onSettled: (_data, _error, variables) => {
      // Refetch to sync with actual state
      queryClient.invalidateQueries({ queryKey: ['host-volumes', variables.hostId] })
    },
  })
}

/**
 * Hook to prune unused volumes from a host
 *
 * Note: Unlike delete operations, prune does NOT use optimistic updates because
 * Docker may not remove all unused volumes (e.g., volumes with special labels).
 * Instead, we update the cache with the actual list of removed volumes from the response.
 */
export function usePruneVolumes(hostId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => pruneVolumes(hostId),
    onSuccess: (data) => {
      // Update cache with actual removed volumes from response
      if (data.volumes_removed && data.volumes_removed.length > 0) {
        const removedSet = new Set(data.volumes_removed)
        const previousVolumes = queryClient.getQueryData<DockerVolume[]>(['host-volumes', hostId])
        if (previousVolumes) {
          queryClient.setQueryData<DockerVolume[]>(
            ['host-volumes', hostId],
            previousVolumes.filter(v => !removedSet.has(v.name))
          )
        }
      }

      if (data.removed_count > 0) {
        const spaceStr = formatBytes(data.space_reclaimed)
        toast.success(`Pruned ${data.removed_count} unused ${pluralize(data.removed_count, 'volume')}, reclaimed ${spaceStr}`)
      } else {
        toast.info('No unused volumes to prune')
      }
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, 'Failed to prune volumes'))
    },
    onSettled: () => {
      // Refetch to sync with actual state
      queryClient.invalidateQueries({ queryKey: ['host-volumes', hostId] })
    },
  })
}

/**
 * Hook to delete multiple volumes from a host (parallel with concurrency limit)
 */
export function useDeleteVolumes() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (params: DeleteVolumesParams) => {
      return batchDeleteWithConcurrency(
        params.volumes,
        async (volume) => {
          const url = `/hosts/${params.hostId}/volumes/${encodeURIComponent(volume.name)}${params.force ? '?force=true' : ''}`
          await apiClient.delete<DeleteVolumeResponse>(url)
          return volume.name
        },
        (volume) => volume.name
      )
    },
    onMutate: async (variables) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['host-volumes', variables.hostId] })

      // Snapshot previous value
      const previousVolumes = queryClient.getQueryData<DockerVolume[]>(['host-volumes', variables.hostId])

      // Optimistically remove deleted volumes from cache
      if (previousVolumes) {
        const deletedNames = new Set(variables.volumes.map(v => v.name))
        queryClient.setQueryData<DockerVolume[]>(
          ['host-volumes', variables.hostId],
          previousVolumes.filter(v => !deletedNames.has(v.name))
        )
      }

      return { previousVolumes }
    },
    onSuccess: (results) => {
      const successCount = results.filter(r => r.success).length
      const failCount = results.filter(r => !r.success).length
      showBulkDeleteToast(successCount, failCount, 'volume')
    },
    onError: (error: unknown, variables, context) => {
      // Rollback on error
      if (context?.previousVolumes) {
        queryClient.setQueryData(['host-volumes', variables.hostId], context.previousVolumes)
      }
      toast.error(getErrorMessage(error, 'Failed to delete volumes'))
    },
    onSettled: (_data, _error, variables) => {
      // Refetch to sync with actual state
      queryClient.invalidateQueries({ queryKey: ['host-volumes', variables.hostId] })
    },
  })
}
