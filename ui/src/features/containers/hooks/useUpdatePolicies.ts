/**
 * Update Policy API Hooks
 *
 * React Query hooks for managing container update validation policies.
 * Follows the established pattern from useContainerUpdates.ts.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type {
  UpdatePoliciesResponse,
  UpdatePolicyValue,
  UpdatePolicyAction,
  ToggleCategoryResponse,
  CreateCustomPatternResponse,
  DeleteCustomPatternResponse,
  UpdatePolicyActionResponse,
  SetContainerPolicyResponse,
  UpdatePolicyCategory
} from '../types/updatePolicy'

/**
 * Query key factory for update policies
 */
export const updatePolicyKeys = {
  all: ['update-policies'] as const,
  lists: () => [...updatePolicyKeys.all, 'list'] as const,
  containerPolicy: (hostId: string, containerId: string) =>
    [...updatePolicyKeys.all, 'container', hostId, containerId] as const
}

/**
 * Get all update validation policies
 *
 * Returns all policies grouped by category with their enabled status.
 */
export function useUpdatePolicies() {
  return useQuery({
    queryKey: updatePolicyKeys.lists(),
    queryFn: async () => {
      const data = await apiClient.get<UpdatePoliciesResponse>('/update-policies')
      return data
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  })
}

/**
 * Toggle all patterns in a category
 *
 * Enables or disables all patterns in the specified category.
 */
export function useTogglePolicyCategory() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      category,
      enabled
    }: {
      category: UpdatePolicyCategory
      enabled: boolean
    }) => {
      const data = await apiClient.put<ToggleCategoryResponse>(
        `/update-policies/${category}/toggle`,
        null,
        { params: { enabled } }
      )
      return data
    },
    onSuccess: () => {
      // Invalidate policies list to refetch
      queryClient.invalidateQueries({ queryKey: updatePolicyKeys.lists() })
    }
  })
}

/**
 * Create a custom update policy pattern
 *
 * Adds a new user-defined pattern to the custom category.
 */
export function useCreateCustomPattern() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ pattern, action = 'warn' }: { pattern: string; action?: UpdatePolicyAction }) => {
      const data = await apiClient.post<CreateCustomPatternResponse>(
        '/update-policies/custom',
        null,
        { params: { pattern, action } }
      )
      return data
    },
    onSuccess: () => {
      // Invalidate policies list to refetch
      queryClient.invalidateQueries({ queryKey: updatePolicyKeys.lists() })
    }
  })
}

/**
 * Delete a custom update policy pattern
 *
 * Removes a user-defined pattern from the custom category.
 * Only custom patterns can be deleted (not built-in patterns).
 */
export function useDeleteCustomPattern() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ policyId }: { policyId: number }) => {
      const data = await apiClient.delete<DeleteCustomPatternResponse>(
        `/update-policies/custom/${policyId}`
      )
      return data
    },
    onSuccess: () => {
      // Invalidate policies list to refetch
      queryClient.invalidateQueries({ queryKey: updatePolicyKeys.lists() })
    }
  })
}

/**
 * Update the action for a policy pattern
 *
 * Changes the action (warn/ignore) for any policy pattern.
 */
export function useUpdatePolicyAction() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ policyId, action }: { policyId: number; action: UpdatePolicyAction }) => {
      const data = await apiClient.put<UpdatePolicyActionResponse>(
        `/update-policies/${policyId}/action`,
        null,
        { params: { action } }
      )
      return data
    },
    onSuccess: () => {
      // Invalidate policies list to refetch
      queryClient.invalidateQueries({ queryKey: updatePolicyKeys.lists() })
    }
  })
}

/**
 * Set per-container update policy override
 *
 * Sets the update policy for a specific container, overriding global patterns.
 */
export function useSetContainerUpdatePolicy() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      hostId,
      containerId,
      policy
    }: {
      hostId: string
      containerId: string
      policy: UpdatePolicyValue
    }) => {
      // Build params object conditionally - omit policy key when null
      const params: Record<string, string> = {}
      if (policy !== null) {
        params.policy = policy
      }

      const data = await apiClient.put<SetContainerPolicyResponse>(
        `/hosts/${hostId}/containers/${containerId}/update-policy`,
        null,
        { params }
      )
      return data
    },
    onSuccess: (_, variables) => {
      // Invalidate container-specific queries
      queryClient.invalidateQueries({
        queryKey: ['container', variables.hostId, variables.containerId]
      })
      // Invalidate update status
      queryClient.invalidateQueries({
        queryKey: ['container-update-status', variables.hostId, variables.containerId]
      })
    }
  })
}
