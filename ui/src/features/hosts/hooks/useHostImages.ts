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
 */
export function usePruneImages(hostId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => pruneImages(hostId),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['host-images', hostId] })
      if (data.removed_count > 0) {
        const sizeInMB = (data.space_reclaimed / (1024 * 1024)).toFixed(1)
        toast.success(`Pruned ${data.removed_count} image${data.removed_count !== 1 ? 's' : ''}, reclaimed ${sizeInMB} MB`)
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
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['host-images', variables.hostId] })
      toast.success(`Delete job started (${variables.imageIds.length} image${variables.imageIds.length !== 1 ? 's' : ''})`)
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error, 'Failed to delete images'))
    },
  })
}
