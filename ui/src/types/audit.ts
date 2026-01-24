/**
 * Audit Log Type Definitions
 *
 * Phase 6 of Multi-User Support (v2.3.0)
 */

// ==================== Action and Entity Type Enums ====================

/**
 * Known audit action types - matches backend AuditAction enum
 */
export const AUDIT_ACTIONS = [
  'login',
  'logout',
  'login_failed',
  'password_change',
  'password_reset_request',
  'password_reset',
  'create',
  'update',
  'delete',
  'start',
  'stop',
  'restart',
  'shell',
  'shell_end',
  'container_update',
  'deploy',
  'settings_change',
  'role_change',
] as const

export type AuditAction = (typeof AUDIT_ACTIONS)[number]

/**
 * Known audit entity types - matches backend AuditEntityType enum
 */
export const AUDIT_ENTITY_TYPES = [
  'session',
  'user',
  'host',
  'container',
  'stack',
  'deployment',
  'alert_rule',
  'notification_channel',
  'tag',
  'registry_credential',
  'health_check',
  'update_policy',
  'api_key',
  'settings',
  'role_permission',
  'oidc_config',
] as const

export type AuditEntityType = (typeof AUDIT_ENTITY_TYPES)[number]

// ==================== Audit Entry Types ====================

export interface AuditLogEntry {
  id: number
  user_id: number | null
  username: string
  action: AuditAction | string  // Allow string for forward compatibility
  entity_type: AuditEntityType | string  // Allow string for forward compatibility
  entity_id: string | null
  entity_name: string | null
  host_id: string | null
  details: Record<string, unknown> | null
  ip_address: string | null
  user_agent: string | null
  created_at: string  // ISO timestamp
}

export interface AuditLogListResponse {
  entries: AuditLogEntry[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// ==================== Filter Types ====================

export interface AuditLogFilters {
  user_id?: number
  username?: string
  action?: string
  entity_type?: string
  entity_id?: string
  search?: string
  start_date?: string  // ISO date
  end_date?: string    // ISO date
}

export interface AuditLogQueryParams extends AuditLogFilters {
  page?: number
  page_size?: number
}

// ==================== Retention Types ====================

export interface RetentionSettingsResponse {
  retention_days: number
  valid_options: number[]
  oldest_entry_date: string | null
  total_entries: number
}

export interface UpdateRetentionRequest {
  retention_days: number
}

export interface RetentionUpdateResponse {
  retention_days: number
  message: string
  entries_to_delete: number
}

// ==================== Stats Types ====================

export interface AuditLogStatsResponse {
  total_entries: number
  entries_by_action: Record<string, number>
  entries_by_entity_type: Record<string, number>
  entries_by_user: Record<string, number>
  oldest_entry_date: string | null
  newest_entry_date: string | null
}

// ==================== User Reference Types ====================

export interface AuditLogUser {
  user_id: number  // Non-null - backend filters out null user_ids
  username: string
}

// ==================== Cleanup Types ====================

export interface CleanupResponse {
  message: string
  deleted_count: number
}

// ==================== Export Types ====================

export interface ExportResult {
  success: boolean
  filename: string
  isTruncated: boolean
  totalMatching: number | null
  included: number | null
}

// ==================== Display Labels ====================

/**
 * Action type labels for display
 */
export const ACTION_LABELS: Record<string, string> = {
  login: 'Login',
  logout: 'Logout',
  login_failed: 'Failed Login',
  password_change: 'Password Change',
  password_reset_request: 'Password Reset Request',
  password_reset: 'Password Reset',
  create: 'Create',
  update: 'Update',
  delete: 'Delete',
  start: 'Start',
  stop: 'Stop',
  restart: 'Restart',
  shell: 'Shell Access',
  shell_end: 'Shell Session End',
  container_update: 'Container Update',
  deploy: 'Deploy',
  settings_change: 'Settings Change',
  role_change: 'Role Change',
}

/**
 * Entity type labels for display
 */
export const ENTITY_TYPE_LABELS: Record<string, string> = {
  session: 'Session',
  user: 'User',
  host: 'Host',
  container: 'Container',
  stack: 'Stack',
  deployment: 'Deployment',
  alert_rule: 'Alert Rule',
  notification_channel: 'Notification Channel',
  tag: 'Tag',
  registry_credential: 'Registry Credential',
  health_check: 'Health Check',
  update_policy: 'Update Policy',
  api_key: 'API Key',
  settings: 'Settings',
  role_permission: 'Role Permission',
  oidc_config: 'OIDC Config',
}

/**
 * Retention period labels for display
 */
export const RETENTION_LABELS: Record<number, string> = {
  30: '30 days',
  60: '60 days',
  90: '90 days',
  180: '180 days (6 months)',
  365: '365 days (1 year)',
  0: 'Unlimited',
}

/**
 * Get action label with fallback
 */
export function getActionLabel(action: string): string {
  return ACTION_LABELS[action] || action
}

/**
 * Get entity type label with fallback
 */
export function getEntityTypeLabel(entityType: string): string {
  return ENTITY_TYPE_LABELS[entityType] || entityType
}
