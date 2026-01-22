/**
 * useHostImages - TanStack Query hooks for host images
 *
 * FEATURES:
 * - useHostImages(): Fetch all images for a host
 * - usePruneImages(): Prune unused images on a host
 * - useDeleteImages(): Batch delete images via batch job
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { getErrorMessage } from '@/lib/utils/errors'
import { formatBytes, pluralize } from '@/lib/utils/formatting'
import type { DockerImage } from '@/types/api'

interface PruneResult {
  removed_count: number
  space_reclaimed: number
}

interface BatchJobResponse {
  job_id: string
}

interface DeleteImagesParams {
  hostId: string
  imageIds: string[]  // Composite keys: {host_id}:{image_id}
  imageNames: Record<string, string>  // Map of composite key to image name/tag
  force?: boolean
}

/**
 * Fetch all images for a host
 */
async function fetchHostImages(hostId: string): Promise<DockerImage[]> {
  return await apiClient.get<DockerImage[]>(`/hosts/${hostId}/images`)
}

/**
 * Prune unused images on a host
 */
async function pruneImages(hostId: string): Promise<PruneResult> {
  return await apiClient.post<PruneResult>(`/hosts/${hostId}/images/prune`)
}

/**
 * Delete images via batch job
 */
async function deleteImages(params: DeleteImagesParams): Promise<BatchJobResponse> {
  return await apiClient.post<BatchJobResponse>('/batch', {
    scope: 'image',
    action: 'delete-images',
    ids: params.imageIds,
    params: {
      force: params.force ?? false,
      image_names: params.imageNames,
    },
  })
}

/**
 * Hook to fetch images for a specific host
 */
export function useHostImages(hostId: string) {
  return useQuery({
    queryKey: ['host-images', hostId],
    queryFn: () => fetchHostImages(hostId),
    enabled: !!hostId,
    staleTime: 30_000, // 30 seconds
  })
}

/**
 * Hook to prune unused images on a host
 *
 * Note: Unlike delete operations, prune does NOT use optimistic updates because
 * Docker may not remove all unused images (e.g., images with special tags).
 * The API doesn't return a list of removed image IDs, so we invalidate the cache after success.
 */
export function usePruneImages(hostId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => pruneImages(hostId),
    onSuccess: (data) => {
      // Invalidate immediately to refresh the list
      queryClient.invalidateQueries({ queryKey: ['host-images', hostId] })

      if (data.removed_count > 0) {
        const spaceStr = formatBytes(data.space_reclaimed)
        toast.success(`Pruned ${data.removed_count} ${pluralize(data.removed_count, 'image')}, reclaimed ${spaceStr}`)
      } else {
        toast.info('No unused images to prune')
      }
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, 'Failed to prune images'))
    },
  })
}

/**
 * Hook to delete images via batch job
 */
export function useDeleteImages() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: deleteImages,
    onMutate: async (variables) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['host-images', variables.hostId] })

      // Snapshot previous value
      const previousImages = queryClient.getQueryData<DockerImage[]>(['host-images', variables.hostId])

      // Optimistically remove deleted images from cache
      if (previousImages) {
        const deletedIds = new Set(variables.imageIds.map(id => id.split(':')[1])) // Extract image ID from composite key
        queryClient.setQueryData<DockerImage[]>(
          ['host-images', variables.hostId],
          previousImages.filter(img => !deletedIds.has(img.id))
        )
      }

      return { previousImages }
    },
    onSuccess: (_data, variables) => {
      toast.success(`Delete job started (${variables.imageIds.length} ${pluralize(variables.imageIds.length, 'image')})`)
    },
    onError: (error: unknown, variables, context) => {
      // Rollback on error
      if (context?.previousImages) {
        queryClient.setQueryData(['host-images', variables.hostId], context.previousImages)
      }
      toast.error(getErrorMessage(error, 'Failed to delete images'))
    },
    onSettled: (_data, _error, variables) => {
      // Refetch after a delay to sync with actual state
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['host-images', variables.hostId] })
      }, 2000)
    },
  })
}
