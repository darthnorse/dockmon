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
  DeploymentType,
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
      // Transform frontend request to match backend API schema
      const backendRequest = {
        name: request.name,
        host_id: request.host_id,
        deployment_type: request.type,  // Backend expects 'deployment_type' not 'type'
        definition: request.definition,
        rollback_on_failure: true,  // Default to true
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
 * Update a deployment's definition (only in 'planning' state)
 */
export function useUpdateDeployment() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      deploymentId,
      name,
      type,
      host_id,
      definition
    }: {
      deploymentId: string;
      name?: string;
      type?: DeploymentType;
      host_id?: string;
      definition: any
    }) => {
      const body: any = { definition }
      if (name) body.name = name
      if (type) body.deployment_type = type
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

// Save as Template mutation
interface SaveAsTemplateRequest {
  deploymentId: string
  name: string
  category: string | null
  description: string | null
}

export function useSaveAsTemplate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: SaveAsTemplateRequest) => {
      const response = await fetch(
        `${API_BASE}/deployments/${request.deploymentId}/save-as-template`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            name: request.name,
            category: request.category,
            description: request.description,
          }),
        }
      )

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to save template')
      }

      return response.json()
    },
    onSuccess: () => {
      // Invalidate templates cache to show new template
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      toast.success('Template created successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to save template: ${error.message}`)
    },
  })
}
