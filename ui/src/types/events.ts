/**
 * Event types for DockMon event logging system
 */

export interface Event {
  id: number
  correlation_id: string | null
  category: EventCategory
  event_type: string
  severity: EventSeverity
  host_id: string | null
  host_name: string | null
  container_id: string | null
  container_name: string | null
  title: string
  message: string | null
  old_state: string | null
  new_state: string | null
  triggered_by: string | null
  details: Record<string, unknown> | null
  duration_ms: number | null
  timestamp: string
}

export type EventCategory = 'container' | 'host' | 'system' | 'alert' | 'notification' | 'user'

export type EventSeverity = 'debug' | 'info' | 'warning' | 'error' | 'critical'

export interface EventsResponse {
  events: Event[]
  total_count: number
  has_more: boolean
}

export interface EventFilters {
  category?: EventCategory[]
  event_type?: string
  severity?: EventSeverity[]
  host_id?: string[]
  container_id?: string[]
  container_name?: string
  start_date?: string
  end_date?: string
  hours?: number
  correlation_id?: string
  search?: string
  limit?: number
  offset?: number
}

export interface EventStatistics {
  total_events: number
  by_severity: Record<EventSeverity, number>
  by_category: Record<EventCategory, number>
  recent_critical: number
  recent_errors: number
}
