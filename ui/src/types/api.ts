/**
 * API Type Definitions
 *
 * NOTE: These are hand-written for v2.0 Phase 2
 * FUTURE: Generate from OpenAPI spec with Orval (when backend adds OpenAPI)
 */

// ==================== Authentication ====================

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  user: {
    id: number
    username: string
    is_first_login: boolean
  }
  message: string
}

export interface CurrentUserResponse {
  user: {
    id: number
    username: string
  }
}

// ==================== User Preferences ====================

export interface UserPreferences {
  theme: 'dark' | 'light'
  group_by: 'env' | 'region' | 'compose' | 'none' | null
  compact_view: boolean
  collapsed_groups: string[]
  filter_defaults: Record<string, unknown>
}

export interface PreferencesUpdate {
  theme?: 'dark' | 'light'
  group_by?: 'env' | 'region' | 'compose' | 'none'
  compact_view?: boolean
  collapsed_groups?: string[]
  filter_defaults?: Record<string, unknown>
}

// ==================== Common ====================

export interface ApiErrorResponse {
  detail: string
}
