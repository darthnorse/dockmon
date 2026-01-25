/**
 * User Management Type Definitions
 *
 * Group-Based Permissions Refactor (v2.4.0)
 */

import type { UserGroupInfo } from './groups'

// ==================== User Types ====================

export type AuthProvider = 'local' | 'oidc'

export interface User {
  id: number
  username: string
  email: string | null
  display_name: string | null
  groups: UserGroupInfo[]  // User's group memberships
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
  group_ids: number[]  // Required: at least one group
  must_change_password?: boolean
}

export interface UpdateUserRequest {
  email?: string | null
  display_name?: string | null
  group_ids?: number[]  // If provided, replaces all groups
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

// ==================== Legacy Role Constants (for migration) ====================
// Re-export from roles.ts for backward compatibility
export { VALID_ROLES as USER_ROLES, ROLE_LABELS, ROLE_DESCRIPTIONS } from './roles'
export type { RoleType as UserRole } from './roles'
