/**
 * React Query hooks for global settings management
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'

export interface GlobalSettings {
  max_retries: number
  retry_delay: number
  default_auto_restart: boolean
  polling_interval: number
  connection_timeout: number
  alert_template: string | null
  alert_template_metric?: string | null
  alert_template_state_change?: string | null
  alert_template_health?: string | null
  alert_template_update?: string | null
  blackout_windows?: Array<{
    name: string
    enabled: boolean
    start_time: string
    end_time: string
    days: number[]
  }> | null
  timezone_offset: number
  show_host_stats: boolean
  show_container_stats: boolean
  show_container_alerts_on_hosts: boolean
  unused_tag_retention_days: number
  event_retention_days: number
  alert_retention_days: number
  update_check_time: string
  skip_compose_containers: boolean
  health_check_timeout_seconds: number
  prune_images_enabled: boolean
  image_retention_count: number
  image_prune_grace_hours: number
}

export interface TemplateVariable {
  name: string
  description: string
}

export interface TemplateVariablesResponse {
  variables: TemplateVariable[]
  default_templates: {
    default: string
    metric: string
    state_change: string
    health: string
    update: string
  }
  examples: Record<string, string>
}

export function useGlobalSettings() {
  return useQuery<GlobalSettings>({
    queryKey: ['global-settings'],
    queryFn: async () => {
      const settings = await apiClient.get<GlobalSettings>('/settings')

      // Always sync browser timezone offset with backend
      // This ensures timestamps are displayed in the user's local timezone
      const browserTimezoneOffset = -new Date().getTimezoneOffset()

      if (settings.timezone_offset !== browserTimezoneOffset) {
        // Update backend with browser's timezone (don't await to avoid slowing down the query)
        apiClient.put('/settings', { timezone_offset: browserTimezoneOffset }).catch(err => {
          console.warn('Failed to sync timezone offset:', err)
        })

        // Update local cache immediately
        settings.timezone_offset = browserTimezoneOffset
      }

      return settings
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

export function useUpdateGlobalSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (updates: Partial<GlobalSettings>) => {
      const result = await apiClient.put<GlobalSettings>('/settings', updates)
      return result
    },
    onSuccess: (updatedSettings) => {
      // Update cache with the returned settings from the server
      queryClient.setQueryData<GlobalSettings>(['global-settings'], updatedSettings)
    },
  })
}

export function useTemplateVariables() {
  return useQuery<TemplateVariablesResponse>({
    queryKey: ['template-variables'],
    queryFn: () => apiClient.get('/notifications/template-variables'),
    staleTime: Infinity, // Template variables never change
  })
}
