/**
 * API Key Types
 * Defines types for API key management
 */

export interface ApiKey {
  id: number
  name: string
  description: string | null
  key_prefix: string // e.g., "dockmon_xxxx..." (safe to display)
  scopes: string // comma-separated: "read,write,admin"
  allowed_ips: string | null // comma-separated IP addresses/CIDRs
  last_used_at: string | null // ISO 8601 datetime
  usage_count: number
  expires_at: string | null // ISO 8601 datetime
  revoked_at: string | null // ISO 8601 datetime (null = active)
  created_at: string // ISO 8601 datetime
}

export interface CreateApiKeyRequest {
  name: string
  description?: string | null
  scopes: string // e.g., "read" or "read,write" or "admin"
  allowed_ips?: string | null // optional IP allowlist
  expires_days?: number | null // optional expiration in days (1-365)
}

export interface CreateApiKeyResponse {
  id: number
  name: string
  key: string // PLAINTEXT KEY - only shown once!
  key_prefix: string
  scopes: string
  expires_at: string | null
  message: string // Warning about saving key
}

export interface UpdateApiKeyRequest {
  name?: string | null
  description?: string | null
  scopes?: string | null
  allowed_ips?: string | null
}

export interface ApiKeyListResponse {
  keys: ApiKey[]
}

/**
 * Scope levels
 */
export type ApiKeyScope = 'read' | 'write' | 'admin'

export interface ScopePreset {
  label: string
  scopes: ApiKeyScope[]
  description: string
  icon: string
  useCase: string
}

/**
 * Scope presets for UI
 */
export const SCOPE_PRESETS: ScopePreset[] = [
  {
    label: 'Read-Only',
    scopes: ['read'],
    description: 'View containers and dashboards',
    icon: '👁️',
    useCase: 'Homepage, monitoring dashboards, read-only access',
  },
  {
    label: 'Read & Write',
    scopes: ['read', 'write'],
    description: 'View and manage containers',
    icon: '✏️',
    useCase: 'Ansible automation, container management scripts',
  },
  {
    label: 'Full Admin',
    scopes: ['admin'],
    description: 'Full access including API key management',
    icon: '🔐',
    useCase: 'Full Access',
  },
]
