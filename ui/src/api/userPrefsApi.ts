/**
 * User Preferences API
 * Handles fetching and updating user preferences
 */

import type { Layout } from 'react-grid-layout'

export interface DashboardPreferences {
  enableCustomLayout: boolean
  hostOrder: string[]
  containerSortKey: 'name' | 'state' | 'cpu' | 'memory' | 'start_time'
  hostContainerSorts?: Record<string, 'name' | 'state' | 'cpu' | 'memory' | 'start_time'>  // Per-host container sort
  hostCardLayout?: Layout[]  // Expanded mode host card layout
  hostCardLayoutStandard?: Layout[]  // Standard mode host card layout
  showKpiBar?: boolean
  showStatsWidgets?: boolean
  optimizedLoading?: boolean
}

export interface UserPreferences {
  theme: string
  group_by?: string
  compact_view: boolean
  collapsed_groups: string[]
  filter_defaults: Record<string, unknown>
  sidebar_collapsed: boolean
  dashboard_layout_v2?: Record<string, unknown>
  dashboard: DashboardPreferences
}

export interface PreferencesUpdate {
  theme?: string
  group_by?: string
  compact_view?: boolean
  collapsed_groups?: string[]
  filter_defaults?: Record<string, unknown>
  sidebar_collapsed?: boolean
  dashboard_layout_v2?: Record<string, unknown>
  dashboard?: Partial<DashboardPreferences>
}

const API_BASE = '/api/v2/user'

export async function getUserPreferences(): Promise<UserPreferences> {
  const response = await fetch(`${API_BASE}/preferences`, {
    credentials: 'include',
  })

  if (!response.ok) {
    throw new Error('Failed to fetch user preferences')
  }

  return response.json()
}

export async function updateUserPreferences(
  updates: PreferencesUpdate
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE}/preferences`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include',
    body: JSON.stringify(updates),
  })

  if (!response.ok) {
    throw new Error('Failed to update user preferences')
  }

  return response.json()
}
