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
  timezone_offset: number
  show_host_stats: boolean
  show_container_stats: boolean
}

export interface TemplateVariable {
  name: string
  description: string
}

export interface TemplateVariablesResponse {
  variables: TemplateVariable[]
  default_template: string
  examples: Record<string, string>
}

export function useGlobalSettings() {
  return useQuery<GlobalSettings>({
    queryKey: ['global-settings'],
    queryFn: () => apiClient.get('/settings'),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

export function useUpdateGlobalSettings() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (updates: Partial<GlobalSettings>) => {
      return apiClient.put('/settings', updates)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['global-settings'] })
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
