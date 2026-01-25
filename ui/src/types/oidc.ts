/**
 * OIDC Types
 * TypeScript interfaces for OIDC configuration and group mappings
 *
 * Group-Based Permissions Refactor (v2.4.0)
 */

// ==================== OIDC Configuration ====================

export interface OIDCConfig {
  enabled: boolean
  provider_url: string | null
  client_id: string | null
  client_secret_configured: boolean
  scopes: string
  claim_for_groups: string
  default_group_id: number | null  // Default group for users with no matching OIDC claims
  default_group_name: string | null  // For display
  created_at: string
  updated_at: string
}

export interface OIDCConfigUpdateRequest {
  enabled?: boolean
  provider_url?: string | null
  client_id?: string | null
  client_secret?: string | null
  scopes?: string | null
  claim_for_groups?: string | null
  default_group_id?: number | null
}

// ==================== OIDC Discovery ====================

export interface OIDCDiscoveryResponse {
  success: boolean
  message: string
  issuer?: string
  authorization_endpoint?: string
  token_endpoint?: string
  userinfo_endpoint?: string
  end_session_endpoint?: string
  scopes_supported?: string[]
  claims_supported?: string[]
}

// ==================== OIDC Group Mappings ====================

export interface OIDCGroupMapping {
  id: number
  oidc_value: string
  group_id: number
  group_name: string  // For display
  priority: number
  created_at: string
}

export interface OIDCGroupMappingCreateRequest {
  oidc_value: string
  group_id: number
  priority?: number
}

export interface OIDCGroupMappingUpdateRequest {
  oidc_value?: string
  group_id?: number
  priority?: number
}

// ==================== OIDC Status (Public) ====================

export interface OIDCStatus {
  enabled: boolean
  provider_configured: boolean
}

// ==================== Legacy Role Types (for migration) ====================
// Re-export from roles.ts for backward compatibility
export { VALID_ROLES as DOCKMON_ROLES, ROLE_LABELS, ROLE_DESCRIPTIONS } from './roles'
export type { RoleType as DockMonRole } from './roles'

// Legacy type aliases for OIDCRoleMapping (now OIDCGroupMapping)
export type OIDCRoleMapping = OIDCGroupMapping
export type OIDCRoleMappingCreateRequest = OIDCGroupMappingCreateRequest
export type OIDCRoleMappingUpdateRequest = OIDCGroupMappingUpdateRequest
