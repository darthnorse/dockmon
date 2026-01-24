/**
 * Role Permissions Types
 * Phase 5 of Multi-User Support (v2.3.0)
 */

// Valid roles
export type RoleType = 'admin' | 'user' | 'readonly'

export const VALID_ROLES: RoleType[] = ['admin', 'user', 'readonly']

export const ROLE_LABELS: Record<RoleType, string> = {
  admin: 'Admin',
  user: 'User',
  readonly: 'Read-only',
}

export const ROLE_DESCRIPTIONS: Record<RoleType, string> = {
  admin: 'Full access to all features',
  user: 'Can operate containers and deploy stacks',
  readonly: 'View only, no modifications',
}

// Capability info from backend
export interface CapabilityInfo {
  name: string
  capability: string
  category: string
  description: string
}

export interface CapabilitiesResponse {
  capabilities: CapabilityInfo[]
  categories: string[]
}

// Role permissions
export interface RolePermissionsResponse {
  permissions: Record<RoleType, Record<string, boolean>>
}

// Permission update
export interface PermissionUpdate {
  role: RoleType
  capability: string
  allowed: boolean
}

export interface UpdatePermissionsRequest {
  permissions: PermissionUpdate[]
}

export interface UpdatePermissionsResponse {
  updated: number
  message: string
}

export interface ResetPermissionsResponse {
  deleted_count: number  // Number of old permissions deleted before reinserting defaults
  message: string
}
