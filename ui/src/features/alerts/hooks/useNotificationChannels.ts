/**
 * React Query hooks for notification channel management
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'

export type ChannelType = 'telegram' | 'discord' | 'slack' | 'teams' | 'google_chat' | 'pushover' | 'gotify' | 'ntfy' | 'smtp' | 'webhook'

// Union of every provider's fields; the backend stores config as opaque JSON
export interface ChannelConfig {
  bot_token?: string
  token?: string
  chat_id?: string
  webhook_url?: string
  url?: string
  app_token?: string
  user_key?: string
  access_token?: string
  server_url?: string
  topic?: string
  smtp_host?: string
  smtp_port?: number
  smtp_user?: string
  smtp_password?: string
  from_email?: string
  to_email?: string
  use_tls?: boolean
  method?: string
  payload_format?: string
  headers?: Record<string, string> | string
}

export interface NotificationChannel {
  id: number
  name: string
  type: ChannelType
  config: ChannelConfig
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ChannelCreateRequest {
  name: string
  type: ChannelType
  config: ChannelConfig
  enabled: boolean
}

export interface ChannelUpdateRequest {
  name?: string
  config?: ChannelConfig
  enabled?: boolean
}

const API_BASE = '/notifications/channels'

export function useNotificationChannels() {
  return useQuery<{ channels: NotificationChannel[] }>({
    queryKey: ['notification-channels'],
    queryFn: async () => {
      const data = await apiClient.get<NotificationChannel[]>(API_BASE)
      return { channels: data }
    },
    staleTime: 60 * 1000, // 1 minute
    refetchOnMount: true, // Always refetch when component mounts to ensure fresh data
  })
}

export function useCreateChannel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (channel: ChannelCreateRequest) => {
      return apiClient.post<NotificationChannel>(API_BASE, channel)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['notification-channels'] })
    },
  })
}

export function useUpdateChannel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ channelId, updates }: { channelId: number; updates: ChannelUpdateRequest }) => {
      return apiClient.put<NotificationChannel>(`${API_BASE}/${channelId}`, updates)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['notification-channels'] })
    },
  })
}

export function useDeleteChannel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (channelId: number) => {
      return apiClient.delete(`${API_BASE}/${channelId}`)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['notification-channels'] })
    },
  })
}

export function useTestChannel() {
  return useMutation({
    mutationFn: async (channelId: number) => {
      return apiClient.post<{ success: boolean; error?: string }>(`${API_BASE}/${channelId}/test`, {})
    },
  })
}

export function useDependentAlerts(channelId: number | null) {
  return useQuery({
    queryKey: ['dependent-alerts', channelId],
    queryFn: async () => {
      if (!channelId) return { alert_count: 0, alert_names: [] }
      return apiClient.get<{ alert_count: number; alert_names: string[] }>(`${API_BASE}/${channelId}/dependent-alerts`)
    },
    enabled: !!channelId,
  })
}
