/**
 * Deployment API Hooks
 *
 * TanStack Query hooks for deployment operations
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import type {
  ImportDeploymentRequest,
  ImportDeploymentResponse,
  ScanComposeDirsRequest,
  ScanComposeDirsResponse,
  ReadComposeFileResponse,
  ComposePreviewResponse,
  GenerateFromContainersRequest,
  RunningProject,
} from '../types'

/**
 * Deploy a stack to a host (fire and forget - no persistent tracking)
 *
 * This is a simplified deployment flow:
 * 1. Call POST /api/deployments/deploy with stack_name and host_id
 * 2. Returns a transient deployment_id for progress tracking
 * 3. No deployment record persisted after completion
 */
export function useDeployStack() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      stack_name,
      host_id,
    }: {
      stack_name: string
      host_id: string
    }): Promise<{ deployment_id: string }> => {
      try {
        const response = await apiClient.post<{ deployment_id: string }>('/deployments/deploy', {
          stack_name,
          host_id,
          force_recreate: true,
          pull_images: true,
        })
        return response
      } catch (error: any) {
        throw new Error(error.data?.detail || error.message || 'Failed to deploy stack')
      }
    },
    onSuccess: () => {
      // Invalidate stacks to refresh deployed_to info
      queryClient.invalidateQueries({ queryKey: ['stacks'] })
    },
    onError: (error: Error) => {
      toast.error(`Failed to deploy: ${error.message}`)
    },
  })
}

// ==================== Import Stack Hooks ====================

/**
 * Import an existing stack
 */
export function useImportDeployment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: ImportDeploymentRequest) => {
      try {
        const response = await apiClient.post<ImportDeploymentResponse>('/deployments/import', request)
        return response
      } catch (error: any) {
        throw new Error(error.data?.detail || error.message || 'Failed to import deployment')
      }
    },
    onSuccess: (result) => {
      // Invalidate stacks list to refetch
      queryClient.invalidateQueries({ queryKey: ['stacks'] })

      if (result.success && result.deployments_created.length > 0) {
        const count = result.deployments_created.length
        const hostText = count === 1 ? '1 host' : `${count} hosts`
        toast.success(`Imported stack to ${hostText}`)
      }
    },
    onError: (error: Error) => {
      toast.error(`Failed to import stack: ${error.message}`)
    },
  })
}

/**
 * Scan directories for compose files on an agent host
 */
export function useScanComposeDirs() {
  return useMutation({
    mutationFn: async ({
      hostId,
      request,
    }: {
      hostId: string
      request?: ScanComposeDirsRequest
    }) => {
      try {
        const response = await apiClient.post<ScanComposeDirsResponse>(
          `/deployments/scan-compose-dirs/${hostId}`,
          request || {}
        )
        return response
      } catch (error: any) {
        throw new Error(error.data?.detail || error.message || 'Failed to scan directories')
      }
    },
    onError: (error: Error) => {
      toast.error(`Failed to scan directories: ${error.message}`)
    },
  })
}

/**
 * Read a compose file's content from an agent host
 */
export function useReadComposeFile() {
  return useMutation({
    mutationFn: async ({
      hostId,
      path,
    }: {
      hostId: string
      path: string
    }) => {
      try {
        const response = await apiClient.post<ReadComposeFileResponse>(
          `/deployments/read-compose-file/${hostId}`,
          { path }
        )
        return response
      } catch (error: any) {
        throw new Error(error.data?.detail || error.message || 'Failed to read compose file')
      }
    },
    onError: (error: Error) => {
      toast.error(`Failed to read compose file: ${error.message}`)
    },
  })
}

// ==================== Generate From Containers Hooks ====================

/**
 * Fetch running Docker Compose projects from container labels.
 * Returns list of projects that can be adopted into DockMon.
 */
export function useRunningProjects() {
  return useQuery({
    queryKey: ['running-projects'],
    queryFn: async () => {
      try {
        const response = await apiClient.get<RunningProject[]>('/deployments/running-projects')
        return response
      } catch (error: any) {
        throw new Error(error.data?.detail || error.message || 'Failed to fetch running projects')
      }
    },
  })
}

/**
 * Generate compose.yaml from running containers with a specific project name
 */
export function useGenerateFromContainers() {
  return useMutation({
    mutationFn: async (request: GenerateFromContainersRequest) => {
      try {
        const response = await apiClient.post<ComposePreviewResponse>('/deployments/generate-from-containers', request)
        return response
      } catch (error: any) {
        throw new Error(error.data?.detail || error.message || 'Failed to generate compose from containers')
      }
    },
    onError: (error: Error) => {
      toast.error(`Failed to generate compose: ${error.message}`)
    },
  })
}
