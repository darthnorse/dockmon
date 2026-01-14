/**
 * Deployment API Hooks
 *
 * TanStack Query hooks for deployment operations
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
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

const API_BASE = '/api'

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
      const response = await fetch(`${API_BASE}/deployments/deploy`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          stack_name,
          host_id,
          force_recreate: true,
          pull_images: true,
        }),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to deploy stack')
      }

      return response.json()
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
      const response = await fetch(`${API_BASE}/deployments/import`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(request),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to import deployment')
      }

      return response.json() as Promise<ImportDeploymentResponse>
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
      const response = await fetch(
        `${API_BASE}/deployments/scan-compose-dirs/${hostId}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'include',
          body: request ? JSON.stringify(request) : '{}',
        }
      )

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to scan directories')
      }

      return response.json() as Promise<ScanComposeDirsResponse>
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
      const response = await fetch(
        `${API_BASE}/deployments/read-compose-file/${hostId}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'include',
          body: JSON.stringify({ path }),
        }
      )

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to read compose file')
      }

      return response.json() as Promise<ReadComposeFileResponse>
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
      const response = await fetch(`${API_BASE}/deployments/running-projects`, {
        credentials: 'include',
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to fetch running projects')
      }

      return response.json() as Promise<RunningProject[]>
    },
  })
}

/**
 * Generate compose.yaml from running containers with a specific project name
 */
export function useGenerateFromContainers() {
  return useMutation({
    mutationFn: async (request: GenerateFromContainersRequest) => {
      const response = await fetch(`${API_BASE}/deployments/generate-from-containers`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(request),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to generate compose from containers')
      }

      return response.json() as Promise<ComposePreviewResponse>
    },
    onError: (error: Error) => {
      toast.error(`Failed to generate compose: ${error.message}`)
    },
  })
}
