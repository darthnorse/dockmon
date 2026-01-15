/**
 * Container Actions Hook
 *
 * Reusable hook for container lifecycle actions (start, stop, restart)
 * Used by ContainerTable, ExpandedHostCard, and other components
 *
 * Keeps buttons disabled until container state actually changes,
 * not just until API returns. This prevents race conditions where
 * API returns before Docker finishes the state transition.
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import type { ContainerAction } from '../types'
import type { ContainerStats } from '@/lib/stats/types'

interface PendingAction {
  expectedState: string
  startedAt: number
}

// Max time to wait for state change before giving up (10 seconds)
const MAX_PENDING_DURATION_MS = 10000

/**
 * Hook for executing container actions with proper error handling
 */
export function useContainerActions(options?: {
  onSuccess?: () => void
}) {
  const queryClient = useQueryClient()

  // Track pending actions per-container with expected state
  // Key: composite key (host_id:container_id)
  // Value: { expectedState, startedAt }
  const [pendingActions, setPendingActions] = useState<Map<string, PendingAction>>(new Map())

  // Ref to track current pending actions for effect cleanup
  const pendingActionsRef = useRef(pendingActions)
  pendingActionsRef.current = pendingActions

  // Watch container state changes to clear pending when state matches expected
  const containers = queryClient.getQueryData<ContainerStats[]>(['containers'])

  useEffect(() => {
    if (!containers || pendingActions.size === 0) return

    const now = Date.now()
    const toRemove: string[] = []

    pendingActions.forEach((action, compositeKey) => {
      // Find the container
      const [hostId, containerId] = compositeKey.split(':')
      const container = containers.find(c => c.id === containerId && c.host_id === hostId)

      if (container) {
        // Check if state matches expected
        const stateMatches = container.state === action.expectedState
        // Check if we've waited too long
        const timedOut = (now - action.startedAt) > MAX_PENDING_DURATION_MS

        if (stateMatches || timedOut) {
          toRemove.push(compositeKey)
        }
      }
    })

    if (toRemove.length > 0) {
      setPendingActions(prev => {
        const next = new Map(prev)
        toRemove.forEach(key => next.delete(key))
        return next
      })
    }
  }, [containers, pendingActions])

  const mutation = useMutation({
    mutationFn: (action: ContainerAction) =>
      apiClient.post(`/hosts/${action.host_id}/containers/${action.container_id}/${action.type}`, {}),

    onMutate: async (action) => {
      const compositeKey = `${action.host_id}:${action.container_id}`

      // Determine expected state after action
      const expectedState = action.type === 'start' ? 'running' :
                           action.type === 'stop' ? 'exited' :
                           action.type === 'restart' ? 'running' :
                           action.type === 'pause' ? 'paused' :
                           action.type === 'unpause' ? 'running' : 'running'

      // Add to pending with expected state
      setPendingActions(prev => {
        const next = new Map(prev)
        next.set(compositeKey, { expectedState, startedAt: Date.now() })
        return next
      })

      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['containers'] })

      // Snapshot for rollback
      const previousContainers = queryClient.getQueryData<ContainerStats[]>(['containers'])

      return { previousContainers, compositeKey }
    },

    onSuccess: (_data, variables) => {
      const actionPastTense: Record<string, string> = {
        start: 'started',
        stop: 'stopped',
        restart: 'restarted',
        pause: 'paused',
        unpause: 'unpaused',
        remove: 'removed',
      }
      const pastTense = actionPastTense[variables.type] || `${variables.type}ed`
      toast.success(`Container ${pastTense} successfully`)
      // Invalidate containers query to refetch with updated started_at timestamp
      queryClient.invalidateQueries({ queryKey: ['containers'] })
      options?.onSuccess?.()
    },

    onError: (error, variables, context) => {
      console.error('[useContainerActions] Action failed:', variables.type, error)
      toast.error(`Failed to ${variables.type} container`, {
        description: error instanceof Error ? error.message : 'Unknown error',
      })

      // Clear pending on error
      if (context?.compositeKey) {
        setPendingActions(prev => {
          const next = new Map(prev)
          next.delete(context.compositeKey)
          return next
        })
      }

      // Rollback optimistic update if we had one
      if (context?.previousContainers) {
        queryClient.setQueryData(['containers'], context.previousContainers)
      }
    },

    // Note: We don't clear pending in onSettled anymore
    // Pending is cleared by the useEffect when state matches expected
  })

  /**
   * Check if a specific container has a pending action
   */
  const isContainerPending = useCallback((hostId: string, containerId: string) => {
    return pendingActions.has(`${hostId}:${containerId}`)
  }, [pendingActions])

  return {
    executeAction: mutation.mutate,
    isPending: mutation.isPending,
    isContainerPending,
    isError: mutation.isError,
    error: mutation.error,
  }
}
