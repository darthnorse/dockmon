/**
 * Container Actions Hook
 *
 * Reusable hook for container lifecycle actions (start, stop, restart)
 * Used by ContainerTable, ExpandedHostCard, and other components
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import type { ContainerAction } from '../types'

/**
 * Hook for executing container actions with proper error handling and query invalidation
 *
 * @param options.onSuccess - Optional callback after successful action
 * @param options.invalidateQueries - Query keys to invalidate (default: ['containers', 'dashboard'])
 */
export function useContainerActions(options?: {
  onSuccess?: () => void
  invalidateQueries?: string[]
}) {
  const queryClient = useQueryClient()
  const queriesToInvalidate = options?.invalidateQueries || ['containers', 'dashboard']

  const mutation = useMutation({
    mutationFn: (action: ContainerAction) =>
      apiClient.post(`/hosts/${action.host_id}/containers/${action.container_id}/${action.type}`, {}),
    onSuccess: (_data, variables) => {
      // Invalidate queries to refresh data
      queriesToInvalidate.forEach(queryKey => {
        queryClient.invalidateQueries({ queryKey: [queryKey] })
      })

      // Show success toast
      const actionLabel = variables.type.charAt(0).toUpperCase() + variables.type.slice(1)
      const actionPastTense: Record<string, string> = {
        start: 'started',
        stop: 'stopped',
        restart: 'restarted',
        pause: 'paused',
        unpause: 'unpaused',
        remove: 'removed',
      }
      const pastTense = actionPastTense[variables.type] || `${variables.type}ed`
      toast.success(`Container ${pastTense} successfully`, {
        description: `Action: ${actionLabel}`,
      })

      // Call optional success callback
      options?.onSuccess?.()
    },
    onError: (error, variables) => {
      debug.error('useContainerActions', `Action ${variables.type} failed:`, error)
      toast.error(`Failed to ${variables.type} container`, {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    },
  })

  return {
    executeAction: mutation.mutate,
    isPending: mutation.isPending,
    isError: mutation.isError,
    error: mutation.error,
  }
}
