/**
 * Stacks API Hooks (v2.2.7+)
 *
 * TanStack Query hooks for filesystem-based stack management.
 * Stacks are stored on filesystem at /app/data/stacks/{name}/
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import type {
  Stack,
  StackListItem,
  CreateStackRequest,
  UpdateStackRequest,
  RenameStackRequest,
  CopyStackRequest,
} from '../types'

const API_BASE = '/api'

/**
 * Fetch all stacks (list view - without content)
 */
export function useStacks() {
  return useQuery({
    queryKey: ['stacks'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE}/stacks`, {
        credentials: 'include',
      })

      if (!response.ok) {
        throw new Error(`Failed to fetch stacks: ${response.statusText}`)
      }

      return response.json() as Promise<StackListItem[]>
    },
  })
}

/**
 * Fetch a single stack by name (with content)
 */
export function useStack(name: string | null) {
  return useQuery({
    queryKey: ['stacks', name],
    queryFn: async () => {
      if (!name) throw new Error('Stack name is required')

      const response = await fetch(`${API_BASE}/stacks/${encodeURIComponent(name)}`, {
        credentials: 'include',
      })

      if (!response.ok) {
        if (response.status === 404) {
          throw new Error('Stack not found')
        }
        throw new Error(`Failed to fetch stack: ${response.statusText}`)
      }

      return response.json() as Promise<Stack>
    },
    enabled: !!name,
  })
}

/**
 * Create a new stack
 */
export function useCreateStack() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateStackRequest) => {
      const response = await fetch(`${API_BASE}/stacks`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(request),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to create stack')
      }

      return response.json() as Promise<Stack>
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stacks'] })
      toast.success('Stack created successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to create stack: ${error.message}`)
    },
  })
}

/**
 * Update an existing stack's content
 */
export function useUpdateStack() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ name, ...request }: UpdateStackRequest & { name: string }) => {
      const response = await fetch(`${API_BASE}/stacks/${encodeURIComponent(name)}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(request),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to update stack')
      }

      return response.json() as Promise<Stack>
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stacks'] })
      queryClient.invalidateQueries({ queryKey: ['stacks', variables.name] })
      toast.success('Stack updated successfully')
    },
    onError: (error: Error) => {
      toast.error(`Failed to update stack: ${error.message}`)
    },
  })
}

/**
 * Delete a stack
 */
export function useDeleteStack() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (name: string) => {
      const response = await fetch(`${API_BASE}/stacks/${encodeURIComponent(name)}`, {
        method: 'DELETE',
        credentials: 'include',
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to delete stack')
      }

      // DELETE returns 204 No Content
      return { success: true }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['stacks'] })
      toast.success('Stack deleted')
    },
    onError: (error: Error) => {
      toast.error(`Failed to delete stack: ${error.message}`)
    },
  })
}

/**
 * Rename a stack
 *
 * Renames the stack directory on the filesystem and updates all
 * deployment references in the database atomically.
 */
export function useRenameStack() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ name, new_name }: { name: string; new_name: string }) => {
      const response = await fetch(`${API_BASE}/stacks/${encodeURIComponent(name)}/rename`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ new_name } as RenameStackRequest),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to rename stack')
      }

      return response.json() as Promise<Stack>
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stacks'] })
      // Invalidate old and new name
      queryClient.invalidateQueries({ queryKey: ['stacks', variables.name] })
      queryClient.invalidateQueries({ queryKey: ['stacks', variables.new_name] })
      // Also invalidate deployments since they reference stack_name
      queryClient.invalidateQueries({ queryKey: ['deployments'] })
      toast.success(`Stack renamed to '${variables.new_name}'`)
    },
    onError: (error: Error) => {
      toast.error(`Failed to rename stack: ${error.message}`)
    },
  })
}

/**
 * Copy a stack to a new name
 */
export function useCopyStack() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ name, dest_name }: { name: string; dest_name: string }) => {
      const response = await fetch(`${API_BASE}/stacks/${encodeURIComponent(name)}/copy`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ dest_name } as CopyStackRequest),
      })

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }))
        throw new Error(error.detail || 'Failed to copy stack')
      }

      return response.json() as Promise<Stack>
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['stacks'] })
      toast.success(`Stack copied to '${variables.dest_name}'`)
    },
    onError: (error: Error) => {
      toast.error(`Failed to copy stack: ${error.message}`)
    },
  })
}
