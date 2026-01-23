/**
 * User Management Type Definitions
 *
 * Phase 3 of Multi-User Support (v2.3.0)
 */

// ==================== User Types ====================

export type UserRole = 'admin' | 'user' | 'readonly'

export type AuthProvider = 'local' | 'oidc'

export interface User {
  id: number
  username: string
  email: string | null
  display_name: string | null
  role: UserRole
  auth_provider: AuthProvider
  is_first_login: boolean
  must_change_password: boolean
  last_login: string | null  // ISO timestamp
  created_at: string  // ISO timestamp
  updated_at: string  // ISO timestamp
  deleted_at: string | null  // ISO timestamp - null = active
  is_deleted: boolean
}

export interface UserListResponse {
  users: User[]
  total: number
}

// ==================== Request Types ====================

export interface CreateUserRequest {
  username: string
  password: string
  email?: string
  display_name?: string
  role?: UserRole
  must_change_password?: boolean
}

export interface UpdateUserRequest {
  email?: string | null
  display_name?: string | null
  role?: UserRole
}

export interface ResetPasswordRequest {
  new_password?: string
}

export interface ResetPasswordResponse {
  message: string
  temporary_password: string | null  // Only set if no password provided
  must_change_password: boolean
}

export interface DeleteUserResponse {
  message: string
}

export interface ReactivateUserResponse extends User {}

// ==================== Role Constants ====================

/**
 * Available user roles - single source of truth
 * Used for role selection in UI components
 */
export const USER_ROLES: readonly UserRole[] = ['admin', 'user', 'readonly'] as const

// ==================== Role Display Helpers ====================

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: 'Admin',
  user: 'User',
  readonly: 'Read-only',
}

export const ROLE_DESCRIPTIONS: Record<UserRole, string> = {
  admin: 'Full access to all features',
  user: 'Can operate containers and deploy stacks',
  readonly: 'View only, no modifications',
}
