/**
 * User Preferences Hook
 * React Query hook for fetching and updating user preferences
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getUserPreferences,
  updateUserPreferences,
  type UserPreferences,
} from '@/api/userPrefsApi'

export function useUserPrefs() {
  const queryClient = useQueryClient()

  const query = useQuery({
    queryKey: ['userPrefs'],
    queryFn: getUserPreferences,
    staleTime: 5 * 60 * 1000, // 5 minutes
  })

  const mutation = useMutation({
    mutationFn: updateUserPreferences,
    onSuccess: () => {
      // Invalidate and refetch
      queryClient.invalidateQueries({ queryKey: ['userPrefs'] })
    },
  })

  return {
    prefs: query.data,
    isLoading: query.isLoading,
    error: query.error,
    updatePrefs: mutation.mutate,
    isUpdating: mutation.isPending,
  }
}

export function useDashboardPrefs() {
  const { prefs, updatePrefs, isUpdating, isLoading } = useUserPrefs()

  const updateDashboardPrefs = (updates: Partial<UserPreferences['dashboard']>) => {
    updatePrefs({
      dashboard: updates,
    })
  }

  return {
    dashboardPrefs: prefs?.dashboard,
    updateDashboardPrefs,
    isUpdating,
    isLoading,
  }
}
