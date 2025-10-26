/**
 * Template API Hooks
 *
 * TanStack Query hooks for deployment template CRUD operations
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import type {
  DeploymentTemplate,
  CreateTemplateRequest,
  UpdateTemplateRequest,
  DeploymentDefinition,
  StackDefinition,
} from '../types'

const API_BASE = '/api'

/**
 * Fetch all templates
 */
export function useTemplates() {
  return useQuery({
    queryKey: ['templates'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/templates`, {
        credentials: 'include',
      })

      if (!response.ok) {
        throw new Error(`Failed to fetch templates: ${response.statusText}`)
      }

      return response.json() as Promise<DeploymentTemplate[]>
    },
  })
}

/**
 * Fetch a single template by ID
 */
export function useTemplate(templateId: string | null) {
  return useQuery({
    queryKey: ['templates', templateId],
    queryFn: async () => {
      if (!templateId) throw new Error('Template ID is required')

      const response = await fetch(`${API_BASE}/templates/${templateId}`, {
        credentials: 'include',
      })

      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Template not found')
        }
        throw new Error(`Failed to fetch template: ${response.statusText}`)
      }

      return response.json() as Promise<DeploymentTemplate>
    },
    enabled: !!templateId,
  })
}

/**
 * Create a new template
 */
export function useCreateTemplate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateTemplateRequest) => {
      const response = await fetch(`${API_BASE}/templates`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(request),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to create template')
      }

      return response.json() as Promise<DeploymentTemplate>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      toast.success('Template created successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to create template: ${error.message}`)
    },
  })
}

/**
 * Update an existing template
 */
export function useUpdateTemplate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ id, ...request }: UpdateTemplateRequest & { id: string }) => {
      const response = await fetch(`${API_BASE}/templates/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(request),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to update template')
      }

      return response.json() as Promise<DeploymentTemplate>
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      queryClient.invalidateQueries({ queryKey: ['templates', variables.id] })
      toast.success('Template updated successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to update template: ${error.message}`)
    },
  })
}

/**
 * Delete a template
 */
export function useDeleteTemplate() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (templateId: string) => {
      const response = await fetch(`${API_BASE}/templates/${templateId}`, {
        method: 'DELETE',
        credentials: 'include',
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to delete template')
      }

      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      toast.success('Template deleted')
    },
    onError: (error: Error) => {
      toast.error(`Failed to delete template: ${error.message}`)
    },
  })
}

/**
 * Render a template with variable substitution
 */
export function useRenderTemplate() {
  return useMutation({
    mutationFn: async ({ templateId, values }: { templateId: string; values: Record<string, any> }) => {
      const response = await fetch(`${API_BASE}/templates/${templateId}/render`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ values }),  // Backend expects "values", not "variables"
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to render template')
      }

      // Backend returns rendered definition directly, not wrapped in RenderedTemplate
      return response.json() as Promise<DeploymentDefinition | StackDefinition>
    },
    onError: (error: Error) => {
      toast.error(`Failed to render template: ${error.message}`)
    },
  })
}
