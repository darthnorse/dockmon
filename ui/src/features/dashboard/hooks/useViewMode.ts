/**
 * useViewMode Hook - Phase 4b
 *
 * Manages dashboard view mode preference (compact | standard | expanded)
 * with auto-default logic and backend persistence
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'

export type ViewMode = 'compact' | 'standard' | 'expanded'

interface ViewModeResponse {
  view_mode: ViewMode
}

/**
 * Fetch view mode from backend
 */
async function fetchViewMode(): Promise<ViewMode> {
  const response = await apiClient.get<ViewModeResponse>('/user/view-mode')
  return response.view_mode
}

/**
 * Save view mode to backend
 */
async function saveViewMode(viewMode: ViewMode): Promise<void> {
  await apiClient.post('/user/view-mode', { view_mode: viewMode })
}

/**
 * Calculate auto-default view mode based on system size
 * Per dockmon_ui_ux.md: If hosts ≤ 10 AND containers ≤ 150 → Expanded, Otherwise → Compact
 */
export function calculateAutoDefault(totalHosts: number, totalContainers: number): ViewMode {
  if (totalHosts <= 10 && totalContainers <= 150) {
    return 'expanded'
  }
  return 'compact'
}

/**
 * Custom hook for view mode management
 */
export function useViewMode() {
  const queryClient = useQueryClient()

  // Fetch current view mode
  const { data: viewMode, isLoading } = useQuery({
    queryKey: ['user', 'viewMode'],
    queryFn: fetchViewMode,
    staleTime: Infinity, // User preference doesn't change often
  })

  // Mutation to save view mode
  const mutation = useMutation({
    mutationFn: saveViewMode,
    onSuccess: (_, newViewMode) => {
      // Optimistically update the cache
      queryClient.setQueryData(['user', 'viewMode'], newViewMode)
    },
  })

  return {
    viewMode: viewMode || 'compact',
    isLoading,
    setViewMode: mutation.mutate,
    isUpdating: mutation.isPending,
  }
}
