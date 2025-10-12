/**
 * useEvents Hook
 *
 * Fetches events from the API with filtering and pagination
 */

import { useQuery, UseQueryResult } from '@tanstack/react-query'
import type { Event, EventsResponse, EventFilters } from '@/types/events'

async function fetchEvents(filters: EventFilters = {}): Promise<EventsResponse> {
  const params = new URLSearchParams()

  // Add array parameters
  if (filters.category) {
    filters.category.forEach((c) => params.append('category', c))
  }
  if (filters.severity) {
    filters.severity.forEach((s) => params.append('severity', s))
  }
  if (filters.host_id) {
    filters.host_id.forEach((h) => params.append('host_id', h))
  }

  // Add single value parameters
  if (filters.event_type) params.set('event_type', filters.event_type)
  if (filters.container_id) params.set('container_id', filters.container_id)
  if (filters.container_name) params.set('container_name', filters.container_name)
  if (filters.start_date) params.set('start_date', filters.start_date)
  if (filters.end_date) params.set('end_date', filters.end_date)
  if (filters.hours !== undefined) params.set('hours', filters.hours.toString())
  if (filters.correlation_id) params.set('correlation_id', filters.correlation_id)
  if (filters.search) params.set('search', filters.search)
  if (filters.limit !== undefined) params.set('limit', filters.limit.toString())
  if (filters.offset !== undefined) params.set('offset', filters.offset.toString())

  const response = await fetch(`/api/events?${params.toString()}`)

  if (!response.ok) {
    throw new Error(`Failed to fetch events: ${response.statusText}`)
  }

  return response.json()
}

export function useEvents(
  filters: EventFilters = {},
  options?: { enabled?: boolean; refetchInterval?: number }
): UseQueryResult<EventsResponse, Error> {
  return useQuery({
    queryKey: ['events', filters],
    queryFn: () => fetchEvents(filters),
    enabled: options?.enabled !== false,
    ...(options?.refetchInterval && { refetchInterval: options.refetchInterval }),
  })
}

/**
 * Hook for fetching events for a specific host
 */
export function useHostEvents(
  hostId: string | undefined,
  limit: number = 50
): UseQueryResult<EventsResponse, Error> {
  return useQuery({
    queryKey: ['host-events', hostId, limit],
    queryFn: async () => {
      if (!hostId) throw new Error('Host ID is required')

      const response = await fetch(`/api/events/host/${hostId}?limit=${limit}`)

      if (!response.ok) {
        throw new Error(`Failed to fetch host events: ${response.statusText}`)
      }

      const data = await response.json()
      return {
        events: data.events,
        total_count: data.total_count,
        has_more: data.total_count > limit,
      }
    },
    enabled: !!hostId,
  })
}

/**
 * Hook for fetching events for a specific container
 */
export function useContainerEvents(
  hostId: string | undefined,
  containerId: string | undefined,
  limit: number = 50
): UseQueryResult<EventsResponse, Error> {
  return useQuery({
    queryKey: ['container-events', hostId, containerId, limit],
    queryFn: async () => {
      if (!hostId || !containerId) {
        throw new Error('Host ID and Container ID are required')
      }

      const response = await fetch(
        `/api/hosts/${hostId}/events/container/${containerId}?limit=${limit}`
      )

      if (!response.ok) {
        throw new Error(`Failed to fetch container events: ${response.statusText}`)
      }

      const data = await response.json()
      return {
        events: data.events,
        total_count: data.total_count,
        has_more: data.total_count > limit,
      }
    },
    enabled: !!hostId && !!containerId,
  })
}

/**
 * Hook for fetching a single event by ID
 */
export function useEvent(eventId: number | undefined): UseQueryResult<Event, Error> {
  return useQuery({
    queryKey: ['event', eventId],
    queryFn: async () => {
      if (!eventId) throw new Error('Event ID is required')

      const response = await fetch(`/api/events/${eventId}`)

      if (!response.ok) {
        throw new Error(`Failed to fetch event: ${response.statusText}`)
      }

      return response.json()
    },
    enabled: !!eventId,
  })
}

/**
 * Hook for fetching related events by correlation ID
 */
export function useCorrelatedEvents(
  correlationId: string | undefined
): UseQueryResult<EventsResponse, Error> {
  return useQuery({
    queryKey: ['correlated-events', correlationId],
    queryFn: async () => {
      if (!correlationId) throw new Error('Correlation ID is required')

      const response = await fetch(`/api/events/correlation/${correlationId}`)

      if (!response.ok) {
        throw new Error(`Failed to fetch correlated events: ${response.statusText}`)
      }

      const data = await response.json()
      return {
        events: data.events,
        total_count: data.count,
        has_more: false,
      }
    },
    enabled: !!correlationId,
  })
}
