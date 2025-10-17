/**
 * User Preferences Hook
 *
 * Database-backed preferences that sync across devices.
 * Replaces localStorage for better multi-device experience.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import type { DashboardLayout } from '@/features/dashboard/types'

export interface UserPreferences {
  theme: string
  group_by: string | null
  compact_view: boolean
  collapsed_groups: string[]
  filter_defaults: Record<string, unknown>

  // React v2 preferences
  sidebar_collapsed: boolean
  dashboard_layout_v2: DashboardLayout | null
  simplified_workflow: boolean

  // Table sorting preferences (TanStack Table format)
  host_table_sort: Array<{ id: string; desc: boolean }> | null
  container_table_sort: Array<{ id: string; desc: boolean }> | null

  // Dashboard preferences
  tagGroupOrder?: string[]
  groupLayouts?: Record<string, any>
  hostContainerSorts?: Record<string, any>
  compactHostOrder?: string[]
  showKpiBar?: boolean
  showStatsWidgets?: boolean
  optimizedLoading?: boolean
  hostCardLayout?: string
  hostCardLayoutStandard?: string

  // Legacy compatibility
  dashboard?: any
}

// Re-export for convenience
export type DashboardLayoutV2 = DashboardLayout

const PREFERENCES_QUERY_KEY = ['user', 'preferences'] as const

/**
 * Fetch user preferences from the database
 */
export function useUserPreferences() {
  return useQuery<UserPreferences>({
    queryKey: PREFERENCES_QUERY_KEY,
    queryFn: () => apiClient.get('/v2/user/preferences'),
    staleTime: 1000 * 60 * 5, // 5 minutes - preferences don't change often
    retry: 1,
  })
}

/**
 * Update user preferences (partial update supported)
 */
export function useUpdatePreferences() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (updates: Partial<UserPreferences>) =>
      apiClient.patch('/v2/user/preferences', updates),

    onMutate: async (updates) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: PREFERENCES_QUERY_KEY })

      // Snapshot previous value
      const previousPreferences =
        queryClient.getQueryData<UserPreferences>(PREFERENCES_QUERY_KEY)

      // Optimistically update
      if (previousPreferences) {
        queryClient.setQueryData<UserPreferences>(PREFERENCES_QUERY_KEY, {
          ...previousPreferences,
          ...updates,
        })
      }

      return { previousPreferences }
    },

    onError: (error, _variables, context) => {
      // Rollback on error
      if (context?.previousPreferences) {
        queryClient.setQueryData(PREFERENCES_QUERY_KEY, context.previousPreferences)
      }
      debug.error('useUpdatePreferences', 'Failed to update preferences:', error)
    },

    onSuccess: () => {
      // Invalidate to ensure we have the latest from server
      queryClient.invalidateQueries({ queryKey: PREFERENCES_QUERY_KEY })
      debug.log('useUpdatePreferences', 'Preferences updated successfully')
    },
  })
}

/**
 * Reset preferences to defaults
 */
export function useResetPreferences() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => apiClient.delete('/v2/user/preferences'),

    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PREFERENCES_QUERY_KEY })
      debug.log('useResetPreferences', 'Preferences reset to defaults')
    },

    onError: (error) => {
      debug.error('useResetPreferences', 'Failed to reset preferences:', error)
    },
  })
}

/**
 * Convenience hook for sidebar state
 */
export function useSidebarCollapsed() {
  const { data: preferences } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()

  const setSidebarCollapsed = (collapsed: boolean) => {
    updatePreferences.mutate({ sidebar_collapsed: collapsed })
  }

  return {
    isCollapsed: preferences?.sidebar_collapsed ?? false,
    setCollapsed: setSidebarCollapsed,
    isLoading: updatePreferences.isPending,
  }
}

/**
 * Convenience hook for dashboard layout
 */
export function useDashboardLayout() {
  const { data: preferences } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()

  const setDashboardLayout = (layout: DashboardLayoutV2) => {
    updatePreferences.mutate({ dashboard_layout_v2: layout })
  }

  return {
    layout: preferences?.dashboard_layout_v2,
    setLayout: setDashboardLayout,
    isLoading: updatePreferences.isPending,
  }
}

/**
 * Convenience hook for simplified workflow setting
 */
export function useSimplifiedWorkflow() {
  const { data: preferences } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()

  const setSimplifiedWorkflow = (enabled: boolean) => {
    updatePreferences.mutate({ simplified_workflow: enabled })
  }

  return {
    enabled: preferences?.simplified_workflow ?? false,
    setEnabled: setSimplifiedWorkflow,
    isLoading: updatePreferences.isPending,
  }
}

/**
 * Legacy hook for backwards compatibility with useUserPrefs
 * @deprecated Use useUserPreferences and useUpdatePreferences directly
 */
export function useUserPrefs() {
  const query = useUserPreferences()
  const mutation = useUpdatePreferences()

  return {
    prefs: query.data,
    isLoading: query.isLoading,
    error: query.error,
    updatePrefs: mutation.mutate,
    isUpdating: mutation.isPending,
  }
}

/**
 * Legacy hook for backwards compatibility
 * @deprecated Use useDashboardLayout instead
 */
export function useDashboardPrefs() {
  const { data: prefs } = useUserPreferences()
  const updatePreferences = useUpdatePreferences()

  const updateDashboardPrefs = (updates: Partial<UserPreferences>) => {
    updatePreferences.mutate(updates)
  }

  return {
    dashboardPrefs: prefs,
    updateDashboardPrefs,
    isUpdating: updatePreferences.isPending,
    isLoading: !prefs,
  }
}
