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

export type StackAction = 'up' | 'down' | 'restart'

interface StackActionParams {
  stack_name: string
  host_id: string
  action: StackAction
  remove_volumes?: boolean
}

/**
 * Perform a stack action (up, down, restart) on a host.
 *
 * This is a simplified deployment flow:
 * 1. Call POST /api/deployments/deploy with stack_name, host_id, and action
 * 2. Returns a transient deployment_id for progress tracking
 * 3. No deployment record persisted after completion
 */
export function useStackAction() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      stack_name,
      host_id,
      action,
      remove_volumes,
    }: StackActionParams): Promise<{ deployment_id: string }> => {
      return apiClient.post<{ deployment_id: string }>('/deployments/deploy', {
        stack_name,
        host_id,
        action,
        force_recreate: action === 'up',
        pull_images: action === 'up',
        remove_volumes,
      })
    },
    onSuccess: () => {
      // Invalidate stacks to refresh deployed_to info
      queryClient.invalidateQueries({ queryKey: ['stacks'] })
    },
    onError: (error: Error) => {
      toast.error(`Failed: ${error.message}`)
    },
  })
}

/**
 * Deploy a stack to a host (fire and forget - no persistent tracking)
 *
 * Convenience wrapper around useStackAction for deploy/redeploy (action="up").
 */
export function useDeployStack() {
  const stackAction = useStackAction()

  // Spread base mutation state, override mutate/mutateAsync to default action to 'up'
  return {
    ...stackAction,
    mutateAsync: ({ stack_name, host_id }: { stack_name: string; host_id: string }) =>
      stackAction.mutateAsync({ stack_name, host_id, action: 'up' }),
    mutate: ({ stack_name, host_id }: { stack_name: string; host_id: string }) =>
      stackAction.mutate({ stack_name, host_id, action: 'up' }),
  }
}

// ==================== Import Stack Hooks ====================

/**
 * Import an existing stack
 */
export function useImportDeployment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: ImportDeploymentRequest) => {
      return apiClient.post<ImportDeploymentResponse>('/deployments/import', request)
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
      return apiClient.post<ScanComposeDirsResponse>(
        `/deployments/scan-compose-dirs/${hostId}`,
        request ?? {},
      )
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
      return apiClient.post<ReadComposeFileResponse>(
        `/deployments/read-compose-file/${hostId}`,
        { path },
      )
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
      return apiClient.get<RunningProject[]>('/deployments/running-projects')
    },
  })
}

/**
 * Generate compose.yaml from running containers with a specific project name
 */
export function useGenerateFromContainers() {
  return useMutation({
    mutationFn: async (request: GenerateFromContainersRequest) => {
      return apiClient.post<ComposePreviewResponse>('/deployments/generate-from-containers', request)
    },
    onError: (error: Error) => {
      toast.error(`Failed to generate compose: ${error.message}`)
    },
  })
}
