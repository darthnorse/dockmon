/**
 * Alert System Types
 */

export type AlertState = 'open' | 'snoozed' | 'resolved'
export type AlertSeverity = 'info' | 'warning' | 'error' | 'critical'
export type AlertScope = 'host' | 'container'

export interface Alert {
  id: string
  dedup_key: string
  scope_type: AlertScope
  scope_id: string
  kind: string
  severity: AlertSeverity
  state: AlertState
  title: string
  message: string
  first_seen: string
  last_seen: string
  occurrences: number
  snoozed_until?: string | null
  resolved_at?: string | null
  resolved_reason?: string | null
  rule_id?: string | null
  rule_version?: number | null
  current_value?: number | null
  threshold?: number | null
  labels?: Record<string, string> | null
  notification_count: number
  host_name?: string | null
  host_id?: string | null
  container_name?: string | null
}

export interface AlertListResponse {
  alerts: Alert[]
  total: number
  page: number
  page_size: number
}

export interface AlertFilters {
  state?: AlertState
  severity?: AlertSeverity
  scope_type?: AlertScope
  scope_id?: string
  rule_id?: string
  page?: number
  page_size?: number
}

export interface AlertAnnotation {
  id: number
  alert_id: string
  timestamp: string
  user?: string | null
  text: string
}

export interface AlertStats {
  total: number
  by_state: {
    open: number
    snoozed: number
    resolved: number
  }
  by_severity: {
    critical: number
    error: number
    warning: number
  }
}

export interface AlertRule {
  id: string
  name: string
  description?: string | null
  scope: AlertScope
  kind: string
  enabled: boolean
  severity: AlertSeverity
  metric?: string | null
  threshold?: number | null
  operator?: string | null
  duration_seconds?: number | null
  occurrences?: number | null
  clear_threshold?: number | null
  clear_duration_seconds?: number | null
  grace_seconds: number
  cooldown_seconds: number
  host_selector_json?: string | null
  container_selector_json?: string | null
  labels_json?: string | null
  notify_channels_json?: string | null
  custom_template?: string | null
  created_at: string
  updated_at: string
  version: number
}

export interface AlertRuleRequest {
  name: string
  description?: string
  scope: AlertScope
  kind: string
  enabled?: boolean
  severity: AlertSeverity
  metric?: string
  threshold?: number
  operator?: string
  duration_seconds?: number
  occurrences?: number
  clear_threshold?: number
  clear_duration_seconds?: number
  grace_seconds?: number
  cooldown_seconds?: number
  host_selector_json?: string
  container_selector_json?: string
  labels_json?: string
  notify_channels_json?: string
  custom_template?: string
}
