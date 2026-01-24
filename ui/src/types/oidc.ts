/**
 * OIDC Types
 * TypeScript interfaces for OIDC configuration and role mappings
 *
 * Phase 4 of Multi-User Support (v2.3.0)
 */

// ==================== OIDC Configuration ====================

export interface OIDCConfig {
  enabled: boolean
  provider_url: string | null
  client_id: string | null
  client_secret_configured: boolean
  scopes: string
  claim_for_groups: string
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

// ==================== OIDC Role Mappings ====================

export interface OIDCRoleMapping {
  id: number
  oidc_value: string
  dockmon_role: string
  priority: number
  created_at: string
}

export interface OIDCRoleMappingCreateRequest {
  oidc_value: string
  dockmon_role: string
  priority?: number
}

export interface OIDCRoleMappingUpdateRequest {
  oidc_value?: string
  dockmon_role?: string
  priority?: number
}

// ==================== OIDC Status (Public) ====================

export interface OIDCStatus {
  enabled: boolean
  provider_configured: boolean
}

// ==================== Role Options ====================

export const DOCKMON_ROLES = ['admin', 'user', 'readonly'] as const
export type DockMonRole = (typeof DOCKMON_ROLES)[number]

export const ROLE_LABELS: Record<DockMonRole, string> = {
  admin: 'Admin',
  user: 'User',
  readonly: 'Read-only',
}

export const ROLE_DESCRIPTIONS: Record<DockMonRole, string> = {
  admin: 'Full access to all features',
  user: 'Can operate containers and deploy stacks',
  readonly: 'View only, no modifications',
}
