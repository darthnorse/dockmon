/**
 * React Query hooks for notification channel management
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'

export interface NotificationChannel {
  id: number
  name: string
  type: 'telegram' | 'discord' | 'slack' | 'pushover' | 'gotify' | 'smtp'
  config: Record<string, any>
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface ChannelCreateRequest {
  name: string
  type: string
  config: Record<string, any>
  enabled: boolean
}

export interface ChannelUpdateRequest {
  name?: string
  config?: Record<string, any>
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
    staleTime: 5 * 60 * 1000, // 5 minutes (notification channels don't change often)
  })
}

export function useCreateChannel() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (channel: ChannelCreateRequest) => {
      return apiClient.post<NotificationChannel>(API_BASE, channel)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notification-channels'] })
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
      queryClient.invalidateQueries({ queryKey: ['notification-channels'] })
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
      queryClient.invalidateQueries({ queryKey: ['notification-channels'] })
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
