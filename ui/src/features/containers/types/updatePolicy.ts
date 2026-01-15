/**
 * Update Policy Types
 *
 * Types for container update validation policies.
 * Supports priority-based validation: labels → per-container → patterns → default allow.
 */

/**
 * Update policy value type
 */
export type UpdatePolicyValue = 'allow' | 'warn' | 'block' | null

/**
 * Update policy action type
 * - 'warn': Show confirmation dialog before update (default)
 * - 'ignore': Skip from automatic update checks (manual checks still allowed)
 */
export type UpdatePolicyAction = 'warn' | 'ignore'

/**
 * Update policy category
 */
export type UpdatePolicyCategory = 'databases' | 'proxies' | 'monitoring' | 'critical' | 'custom'

/**
 * Single update policy pattern
 */
export interface UpdatePolicy {
  id: number
  pattern: string
  enabled: boolean
  action: UpdatePolicyAction
  created_at: string | null
  updated_at: string | null
}

/**
 * Update policies grouped by category
 */
export interface UpdatePoliciesResponse {
  categories: {
    [key in UpdatePolicyCategory]?: UpdatePolicy[]
  }
}

/**
 * Validation result from update attempt
 */
export interface UpdateValidationResponse {
  validation: 'allow' | 'warn' | 'block'
  reason: string
  matched_pattern?: string
}

/**
 * Response from toggle category endpoint
 */
export interface ToggleCategoryResponse {
  success: boolean
  category: string
  enabled: boolean
  patterns_affected: number
}

/**
 * Response from create custom pattern endpoint
 */
export interface CreateCustomPatternResponse {
  success: boolean
  id: number
  pattern: string
}

/**
 * Response from delete custom pattern endpoint
 */
export interface DeleteCustomPatternResponse {
  success: boolean
  deleted_pattern: string
}

/**
 * Response from update policy action endpoint
 */
export interface UpdatePolicyActionResponse {
  success: boolean
  id: number
  pattern: string
  action: UpdatePolicyAction
}

/**
 * Response from set container policy endpoint
 */
export interface SetContainerPolicyResponse {
  success: boolean
  host_id: string
  container_id: string
  update_policy: UpdatePolicyValue
}

/**
 * Category display metadata
 */
export interface CategoryMetadata {
  category: UpdatePolicyCategory
  label: string
  description: string
  icon: string
  color: string
}

/**
 * Category metadata for UI display
 */
export const CATEGORY_METADATA: Record<UpdatePolicyCategory, CategoryMetadata> = {
  databases: {
    category: 'databases',
    label: 'Databases',
    description: 'Database containers (postgres, mysql, mongodb, etc.)',
    icon: 'database',
    color: 'text-blue-400'
  },
  proxies: {
    category: 'proxies',
    label: 'Proxies',
    description: 'Reverse proxy and ingress containers (traefik, nginx, caddy)',
    icon: 'network',
    color: 'text-purple-400'
  },
  monitoring: {
    category: 'monitoring',
    label: 'Monitoring',
    description: 'Monitoring and observability containers (grafana, prometheus)',
    icon: 'activity',
    color: 'text-green-400'
  },
  critical: {
    category: 'critical',
    label: 'Critical',
    description: 'Critical infrastructure containers (portainer, dockmon)',
    icon: 'alert-triangle',
    color: 'text-red-400'
  },
  custom: {
    category: 'custom',
    label: 'Custom Patterns',
    description: 'User-defined patterns',
    icon: 'plus-circle',
    color: 'text-gray-400'
  }
}

/**
 * Policy selector options for dropdown
 */
export const POLICY_OPTIONS: Array<{ value: UpdatePolicyValue; label: string; description: string }> = [
  {
    value: null,
    label: 'Use Global Settings',
    description: 'Use global patterns and Docker labels'
  },
  {
    value: 'allow',
    label: 'Always Allow',
    description: 'Always allow updates without warnings'
  },
  {
    value: 'warn',
    label: 'Warn Before Update',
    description: 'Require confirmation before updating'
  },
  {
    value: 'block',
    label: 'Block Updates',
    description: 'Prevent automatic updates completely'
  }
]

/**
 * Action options for pattern action dropdown
 */
export const ACTION_OPTIONS: Array<{ value: UpdatePolicyAction; label: string; description: string }> = [
  {
    value: 'warn',
    label: 'Warn',
    description: 'Show confirmation dialog before update'
  },
  {
    value: 'ignore',
    label: 'Ignore',
    description: 'Skip from automatic update checks'
  }
]
