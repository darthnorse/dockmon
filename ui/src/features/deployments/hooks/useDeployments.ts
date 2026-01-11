/**
 * Deployment API Hooks
 *
 * TanStack Query hooks for deployment CRUD operations
 * Follows same patterns as container hooks
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import type {
  Deployment,
  DeploymentFilters,
  CreateDeploymentRequest,
  KnownStack,
  ImportDeploymentRequest,
  ImportDeploymentResponse,
  ScanComposeDirsRequest,
  ScanComposeDirsResponse,
  ReadComposeFileResponse,
} from '../types'

const API_BASE = '/api'

/**
 * Fetch all deployments with optional filters
 */
export function useDeployments(filters?: DeploymentFilters) {
  return useQuery({
    queryKey: ['deployments', filters],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (filters?.host_id) params.set('host_id', filters.host_id)
      if (filters?.status) params.set('status', filters.status)
      if (filters?.limit) params.set('limit', filters.limit.toString())
      if (filters?.offset) params.set('offset', filters.offset.toString())

      const url = `${API_BASE}/deployments${params.toString() ? `?${params}` : ''}`
      const response = await fetch(url, {
        credentials: 'include',
      })

      if (!response.ok) {
        throw new Error(`Failed to fetch deployments: ${response.statusText}`)
      }

      return response.json() as Promise<Deployment[]>
    },
  })
}

/**
 * Fetch a single deployment by ID
 */
export function useDeployment(deploymentId: string | null) {
  return useQuery({
    queryKey: ['deployments', deploymentId],
    queryFn: async () => {
      if (!deploymentId) throw new Error('Deployment ID is required')

      const response = await fetch(`${API_BASE}/deployments/${deploymentId}`, {
        credentials: 'include',
      })

      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Deployment not found')
        }
        throw new Error(`Failed to fetch deployment: ${response.statusText}`)
      }

      return response.json() as Promise<Deployment>
    },
    enabled: !!deploymentId,
  })
}

/**
 * Create a new deployment
 */
export function useCreateDeployment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateDeploymentRequest) => {
      // v2.2.7+: Deployments reference stacks by name
      const backendRequest = {
        stack_name: request.stack_name,
        host_id: request.host_id,
        rollback_on_failure: request.rollback_on_failure ?? true,
      }

      const response = await fetch(`${API_BASE}/deployments`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(backendRequest),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to create deployment')
      }

      return response.json() as Promise<Deployment>
    },
    onSuccess: () => {
      // Invalidate deployments list to refetch
      queryClient.invalidateQueries({ queryKey: ['deployments'] })
      toast.success('Deployment created successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to create deployment: ${error.message}`)
    },
  })
}

/**
 * Execute a deployment
 */
export function useExecuteDeployment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (deploymentId: string) => {
      const response = await fetch(`${API_BASE}/deployments/${deploymentId}/execute`, {
        method: 'POST',
        credentials: 'include',
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to execute deployment')
      }

      return response.json()
    },
    onSuccess: (_, deploymentId) => {
      // Invalidate specific deployment to refetch
      queryClient.invalidateQueries({ queryKey: ['deployments', deploymentId] })
      queryClient.invalidateQueries({ queryKey: ['deployments'] })
      toast.success('Deployment execution started')
    },
    onError: (error: Error) => {
      toast.error(`Failed to execute deployment: ${error.message}`)
    },
  })
}

/**
 * Redeploy a running stack (force recreate containers with latest images)
 */
export function useRedeployDeployment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (deploymentId: string) => {
      const response = await fetch(`${API_BASE}/deployments/${deploymentId}/execute`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({
          force_recreate: true,
          pull_images: true,
        }),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to redeploy')
      }

      return response.json()
    },
    onSuccess: (_, deploymentId) => {
      // Invalidate specific deployment to refetch
      queryClient.invalidateQueries({ queryKey: ['deployments', deploymentId] })
      queryClient.invalidateQueries({ queryKey: ['deployments'] })
      toast.success('Redeployment started - pulling latest images and recreating containers')
    },
    onError: (error: Error) => {
      toast.error(`Failed to redeploy: ${error.message}`)
    },
  })
}

/**
 * Update a deployment's target stack or host (v2.2.7+).
 * Allowed in: 'planning', 'failed', 'rolled_back', 'partial', or 'running' states.
 *
 * Note: To update compose content, use PUT /api/stacks/{name} instead.
 * This endpoint only changes which stack or host a deployment references.
 */
export function useUpdateDeployment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      deploymentId,
      stack_name,
      host_id,
    }: {
      deploymentId: string
      stack_name?: string
      host_id?: string
    }) => {
      const body: { stack_name?: string; host_id?: string } = {}
      if (stack_name) body.stack_name = stack_name
      if (host_id) body.host_id = host_id

      const response = await fetch(`${API_BASE}/deployments/${deploymentId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(body),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to update deployment')
      }

      return response.json() as Promise<Deployment>
    },
    onSuccess: (_, { deploymentId }) => {
      // Invalidate specific deployment and list
      queryClient.invalidateQueries({ queryKey: ['deployments', deploymentId] })
      queryClient.invalidateQueries({ queryKey: ['deployments'] })
      toast.success('Deployment updated successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to update deployment: ${error.message}`)
    },
  })
}

/**
 * Delete a deployment
 */
export function useDeleteDeployment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (deploymentId: string) => {
      const response = await fetch(`${API_BASE}/deployments/${deploymentId}`, {
        method: 'DELETE',
        credentials: 'include',
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to delete deployment')
      }

      return response.json()
    },
    onSuccess: () => {
      // Invalidate deployments list
      queryClient.invalidateQueries({ queryKey: ['deployments'] })
      toast.success('Deployment deleted')
    },
    onError: (error: Error) => {
      toast.error(`Failed to delete deployment: ${error.message}`)
    },
  })
}

// ==================== Import Stack Hooks ====================

/**
 * Fetch known stacks from container labels
 */
export function useKnownStacks() {
  return useQuery({
    queryKey: ['known-stacks'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/deployments/known-stacks`, {
        credentials: 'include',
      })

      if (!response.ok) {
        throw new Error(`Failed to fetch known stacks: ${response.statusText}`)
      }

      return response.json() as Promise<KnownStack[]>
    },
  })
}

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
      // Invalidate deployments list to refetch
      queryClient.invalidateQueries({ queryKey: ['deployments'] })

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
