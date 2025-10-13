/**
 * React Query hooks for Alert API
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Alert, AlertListResponse, AlertFilters, AlertStats, AlertAnnotation } from '@/types/alerts'

const API_BASE = '/api/alerts'

// Fetch alerts with filters
export function useAlerts(filters: AlertFilters = {}, options = {}) {
  const queryParams = new URLSearchParams()

  if (filters.state) queryParams.append('state', filters.state)
  if (filters.severity) queryParams.append('severity', filters.severity)
  if (filters.scope_type) queryParams.append('scope_type', filters.scope_type)
  if (filters.scope_id) queryParams.append('scope_id', filters.scope_id)
  if (filters.rule_id) queryParams.append('rule_id', filters.rule_id)
  if (filters.page) queryParams.append('page', filters.page.toString())
  if (filters.page_size) queryParams.append('page_size', filters.page_size.toString())

  return useQuery<AlertListResponse>({
    queryKey: ['alerts', filters],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/?${queryParams}`)
      if (!res.ok) throw new Error('Failed to fetch alerts')
      return res.json()
    },
    ...options,
  })
}

// Fetch single alert
export function useAlert(alertId: string | null) {
  return useQuery<Alert>({
    queryKey: ['alert', alertId],
    queryFn: async () => {
      if (!alertId) throw new Error('Alert ID required')
      const res = await fetch(`${API_BASE}/${alertId}`)
      if (!res.ok) throw new Error('Failed to fetch alert')
      return res.json()
    },
    enabled: !!alertId,
  })
}

// Fetch alert stats
export function useAlertStats() {
  return useQuery<AlertStats>({
    queryKey: ['alert-stats'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE}/stats/`)
      if (!res.ok) throw new Error('Failed to fetch alert stats')
      return res.json()
    },
    refetchInterval: 30000, // Refresh every 30 seconds
  })
}

// Fetch alert annotations
export function useAlertAnnotations(alertId: string | null) {
  return useQuery<{ annotations: AlertAnnotation[] }>({
    queryKey: ['alert-annotations', alertId],
    queryFn: async () => {
      if (!alertId) throw new Error('Alert ID required')
      const res = await fetch(`${API_BASE}/${alertId}/annotations`)
      if (!res.ok) throw new Error('Failed to fetch annotations')
      return res.json()
    },
    enabled: !!alertId,
  })
}

// Resolve alert mutation
export function useResolveAlert() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ alertId, reason }: { alertId: string; reason?: string }) => {
      const res = await fetch(`${API_BASE}/${alertId}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: reason || 'Manually resolved' }),
      })
      if (!res.ok) throw new Error('Failed to resolve alert')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ['alert-stats'] })
    },
  })
}

// Snooze alert mutation
export function useSnoozeAlert() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ alertId, durationMinutes }: { alertId: string; durationMinutes: number }) => {
      const res = await fetch(`${API_BASE}/${alertId}/snooze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ duration_minutes: durationMinutes }),
      })
      if (!res.ok) throw new Error('Failed to snooze alert')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ['alert-stats'] })
    },
  })
}

// Unsnooze alert mutation
export function useUnsnoozeAlert() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (alertId: string) => {
      const res = await fetch(`${API_BASE}/${alertId}/unsnooze`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error('Failed to unsnooze alert')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ['alert-stats'] })
    },
  })
}

// Add annotation mutation
export function useAddAnnotation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({ alertId, text, user }: { alertId: string; text: string; user?: string }) => {
      const res = await fetch(`${API_BASE}/${alertId}/annotations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, user }),
      })
      if (!res.ok) throw new Error('Failed to add annotation')
      return res.json()
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ['alert-annotations', variables.alertId] })
    },
  })
}
