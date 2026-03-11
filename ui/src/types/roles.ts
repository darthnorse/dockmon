/**
 * Capability Types
 * Group-Based Permissions Refactor (v2.4.0)
 *
 * Capabilities are now assigned to groups, not roles.
 * See types/groups.ts for group permission types.
 */

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

// ==================== Legacy Types (for migration) ====================
// These are kept for backward compatibility during the transition period

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

/**
 * @deprecated Use group permissions instead
 */
export interface RolePermissionsResponse {
  permissions: Record<RoleType, Record<string, boolean>>
}

/**
 * @deprecated Use group permissions instead
 */
export interface PermissionUpdate {
  role: RoleType
  capability: string
  allowed: boolean
}

/**
 * @deprecated Use group permissions instead
 */
export interface UpdatePermissionsRequest {
  permissions: PermissionUpdate[]
}

/**
 * @deprecated Use group permissions instead
 */
export interface UpdatePermissionsResponse {
  updated: number
  message: string
}

/**
 * @deprecated Use group permissions instead
 */
export interface ResetPermissionsResponse {
  deleted_count: number
  message: string
}
