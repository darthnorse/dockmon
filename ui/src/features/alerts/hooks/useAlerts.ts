/**
 * React Query hooks for Alert API
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { Alert, AlertListResponse, AlertFilters, AlertStats, AlertAnnotation } from '@/types/alerts'
import type { EventsResponse } from '@/types/events'

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

// Fetch all open alerts for badge display (batched)
// Returns a Map of scope_id -> severity breakdown for efficient lookup
export interface AlertSeverityCounts {
  critical: number
  error: number
  warning: number
  info: number
  total: number
  alerts: Alert[]  // Store actual alerts for linking
}

export function useAlertCounts(scope_type: 'container' | 'host') {
  return useQuery({
    queryKey: ['alert-counts', scope_type],
    queryFn: async () => {
      // Fetch all open alerts for this scope type (no pagination)
      const queryParams = new URLSearchParams()
      queryParams.append('state', 'open')
      queryParams.append('scope_type', scope_type)
      queryParams.append('page_size', '500') // Large limit to get all alerts in one request

      const res = await fetch(`${API_BASE}/?${queryParams}`)
      if (!res.ok) throw new Error('Failed to fetch alert counts')
      const data: AlertListResponse = await res.json()

      // Build a Map of scope_id -> severity breakdown
      const counts = new Map<string, AlertSeverityCounts>()
      data.alerts.forEach(alert => {
        if (!counts.has(alert.scope_id)) {
          counts.set(alert.scope_id, {
            critical: 0,
            error: 0,
            warning: 0,
            info: 0,
            total: 0,
            alerts: []
          })
        }
        const scopeCounts = counts.get(alert.scope_id)!
        scopeCounts.total++
        scopeCounts.alerts.push(alert)

        // Count by severity
        switch (alert.severity.toLowerCase()) {
          case 'critical':
            scopeCounts.critical++
            break
          case 'error':
            scopeCounts.error++
            break
          case 'warning':
            scopeCounts.warning++
            break
          case 'info':
            scopeCounts.info++
            break
        }
      })

      return counts
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

// Fetch host alert counts, optionally including container alerts aggregated by host
// Returns a Map keyed by both hostId and hostname for flexible lookups
export function useHostAlertCounts(includeContainerAlerts: boolean = false) {
  const hostAlertsQuery = useAlertCounts('host')
  const containerAlertsQuery = useAlertCounts('container')

  return useQuery<Map<string, AlertSeverityCounts>>({
    queryKey: ['host-alert-counts', includeContainerAlerts],
    queryFn: () => {
      const hostCounts = hostAlertsQuery.data || new Map()

      if (!includeContainerAlerts) {
        return hostCounts
      }

      // Build a map by hostname first, then we'll need to look up by hostId in the component
      const containerCounts = containerAlertsQuery.data || new Map()
      const aggregatedByHostname = new Map<string, AlertSeverityCounts>()

      // First, copy host alerts by hostname
      hostCounts.forEach((counts, _hostId) => {
        counts.alerts.forEach((alert: Alert) => {
          if (!alert.host_name) return

          if (!aggregatedByHostname.has(alert.host_name)) {
            aggregatedByHostname.set(alert.host_name, {
              critical: 0,
              error: 0,
              warning: 0,
              info: 0,
              total: 0,
              alerts: []
            })
          }

          const hostnameCounts = aggregatedByHostname.get(alert.host_name)!
          hostnameCounts.total++
          hostnameCounts.alerts.push(alert)

          switch (alert.severity.toLowerCase()) {
            case 'critical': hostnameCounts.critical++; break
            case 'error': hostnameCounts.error++; break
            case 'warning': hostnameCounts.warning++; break
            case 'info': hostnameCounts.info++; break
          }
        })
      })

      // Then add container alerts by hostname
      containerCounts.forEach((counts, _containerId) => {
        counts.alerts.forEach((alert: Alert) => {
          if (!alert.host_name) return

          if (!aggregatedByHostname.has(alert.host_name)) {
            aggregatedByHostname.set(alert.host_name, {
              critical: 0,
              error: 0,
              warning: 0,
              info: 0,
              total: 0,
              alerts: []
            })
          }

          const hostnameCounts = aggregatedByHostname.get(alert.host_name)!
          hostnameCounts.total++
          hostnameCounts.alerts.push(alert)

          switch (alert.severity.toLowerCase()) {
            case 'critical': hostnameCounts.critical++; break
            case 'error': hostnameCounts.error++; break
            case 'warning': hostnameCounts.warning++; break
            case 'info': hostnameCounts.info++; break
          }
        })
      })

      return aggregatedByHostname
    },
    enabled: hostAlertsQuery.isSuccess && (!includeContainerAlerts || containerAlertsQuery.isSuccess),
    refetchInterval: 30000,
  })
}

// Fetch events related to an alert based on its scope
export function useAlertEvents(alert: Alert | null | undefined) {
  return useQuery<EventsResponse>({
    queryKey: ['alert-events', alert?.scope_type, alert?.scope_id],
    queryFn: async () => {
      if (!alert) throw new Error('Alert required')

      const queryParams = new URLSearchParams()

      // Filter events by scope
      if (alert.scope_type === 'container') {
        queryParams.append('container_id', alert.scope_id)
      } else if (alert.scope_type === 'host') {
        queryParams.append('host_id', alert.scope_id)
      }

      // Get events from the past 24 hours or since alert first seen (whichever is longer, minimum 2 hours)
      // Add 1 hour buffer to account for timing differences and ensure we catch all related events
      const alertAge = Date.now() - new Date(alert.first_seen).getTime()
      const alertAgeHours = Math.ceil(alertAge / (1000 * 60 * 60))
      const hoursToFetch = Math.max(2, Math.min(alertAgeHours + 1, 24)) // Between 2-24 hours with +1hr buffer
      queryParams.append('hours', hoursToFetch.toString())

      // Limit to recent events
      queryParams.append('limit', '20')

      const res = await fetch(`/api/events?${queryParams}`)
      if (!res.ok) {
        const errorText = await res.text()
        throw new Error(`Failed to fetch alert events: ${errorText}`)
      }
      return res.json()
    },
    enabled: !!alert && !!alert.scope_id,
  })
}
