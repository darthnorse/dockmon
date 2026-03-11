/**
 * Stacks API Hooks (v2.2.7+)
 *
 * TanStack Query hooks for filesystem-based stack management.
 * Stacks are stored on filesystem at /app/data/stacks/{name}/
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import type {
  Stack,
  StackListItem,
  CreateStackRequest,
  UpdateStackRequest,
  RenameStackRequest,
  CopyStackRequest,
} from '../types'

/**
 * Fetch all stacks (list view - without content)
 */
export function useStacks() {
  return useQuery({
    queryKey: ['stacks'],
    queryFn: async () => {
      return apiClient.get<StackListItem[]>('/stacks')
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

      return apiClient.get<Stack>(`/stacks/${encodeURIComponent(name)}`)
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
      return apiClient.post<Stack>('/stacks', request)
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
      return apiClient.put<Stack>(`/stacks/${encodeURIComponent(name)}`, request)
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
      return apiClient.delete<{ success: boolean }>(`/stacks/${encodeURIComponent(name)}`)
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
      return apiClient.put<Stack>(
        `/stacks/${encodeURIComponent(name)}/rename`,
        { new_name } as RenameStackRequest
      )
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
      return apiClient.post<Stack>(
        `/stacks/${encodeURIComponent(name)}/copy`,
        { dest_name } as CopyStackRequest
      )
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
