/**
 * Deployment Types - v2.2.8
 *
 * Type definitions for stacks and deployments
 * Stacks are filesystem-based compose configurations
 * Deployed hosts are derived from container labels (com.docker.compose.project)
 */

/**
 * Deployment status values from backend state machine
 */
export type DeploymentStatus =
  | 'planning'        // Initial state after creation
  | 'validating'      // Security validation in progress
  | 'pulling_image'   // Pulling Docker image
  | 'creating'        // Creating container
  | 'starting'        // Starting container
  | 'running'         // Container running successfully (terminal state)
  | 'partial'         // Some services running, others failed (terminal state)
  | 'failed'          // Failed during execution
  | 'rolled_back'     // Failed and rolled back (before commitment point)
  | 'stopped'         // Imported stack with no running containers

// ==================== Stack Types ====================

/**
 * Host where a stack is deployed (from container labels)
 */
export interface DeployedHost {
  host_id: string
  host_name: string
}

/**
 * Stack from the Stacks API (filesystem-based)
 * GET /api/stacks/{name} returns full content
 * GET /api/stacks returns list without content
 *
 * deployed_to is derived from running containers with matching
 * com.docker.compose.project labels - not from database records.
 */
export interface Stack {
  name: string                  // Stack name (lowercase alphanumeric, hyphens, underscores)
  deployed_to: DeployedHost[]   // Hosts where this stack is running (from container labels)
  compose_yaml?: string         // Docker Compose YAML content (optional in list, present in detail)
  env_content?: string | null   // Optional .env file content
}

/**
 * Stack list item (without content) - for list view performance
 */
export interface StackListItem {
  name: string
  deployed_to: DeployedHost[]
}

/**
 * Request to create a new stack
 */
export interface CreateStackRequest {
  name: string
  compose_yaml: string
  env_content?: string | null
}

/**
 * Request to update a stack's content
 */
export interface UpdateStackRequest {
  compose_yaml: string
  env_content?: string | null
}

/**
 * Request to rename a stack
 */
export interface RenameStackRequest {
  new_name: string
}

/**
 * Request to copy a stack
 */
export interface CopyStackRequest {
  dest_name: string
}

// ==================== Stack Validation Utilities ====================

/**
 * Stack name validation pattern (must match backend)
 * - Lowercase alphanumeric
 * - Can contain hyphens and underscores
 * - Must start with letter or number
 */
export const VALID_STACK_NAME_PATTERN = /^[a-z0-9][a-z0-9_-]*$/

/**
 * Maximum length for stack names
 */
export const MAX_STACK_NAME_LENGTH = 100

/**
 * Validate a stack name and return error message if invalid
 * @param name - Stack name to validate
 * @returns Error message if invalid, null if valid
 */
export function validateStackName(name: string): string | null {
  const trimmed = name.trim()

  if (!trimmed) {
    return 'Stack name is required'
  }

  if (!VALID_STACK_NAME_PATTERN.test(trimmed)) {
    return 'Stack name must be lowercase alphanumeric, starting with a letter or number'
  }

  if (trimmed.length > MAX_STACK_NAME_LENGTH) {
    return `Stack name must be ${MAX_STACK_NAME_LENGTH} characters or less`
  }

  return null
}

// ==================== Deployment Types ====================

/**
 * Deployment object returned by import API
 * Used to track imported stacks and their metadata
 */
export interface Deployment {
  id: string                    // Deployment UUID
  host_id: string               // UUID of target Docker host
  host_name?: string            // Optional: host display name
  stack_name: string            // References stack in /api/stacks/{stack_name}
  status: DeploymentStatus      // Current state in state machine

  // Progress tracking
  progress_percent: number      // 0-100
  current_stage: string | null  // e.g., "pulling", "creating", "starting"
  error_message: string | null  // Error details if status is 'failed'

  // State machine metadata
  committed: boolean            // Whether commitment point was reached
  rollback_on_failure: boolean  // Auto-rollback on deployment failure
  created_by?: string | null    // Username who created deployment

  // Container tracking
  container_ids?: string[]      // SHORT container IDs (12 chars) for running deployments

  // Timestamps
  created_at: string            // ISO timestamp with 'Z' suffix
  updated_at: string | null     // ISO timestamp with 'Z' suffix
  started_at?: string | null    // ISO timestamp with 'Z' suffix
  completed_at: string | null   // ISO timestamp with 'Z' suffix
}

// ==================== Import Stack Types ====================

/**
 * A stack discovered from container labels (from GET /known-stacks)
 */
export interface KnownStack {
  name: string
  hosts: string[]
  host_names: string[]
  container_count: number
  services: string[]
}

/**
 * API request to import an existing stack
 */
export interface ImportDeploymentRequest {
  compose_content: string
  env_content?: string
  project_name?: string
  host_id?: string
  overwrite_stack?: boolean
  use_existing_stack?: boolean
}

/**
 * API response from import operation
 */
export interface ImportDeploymentResponse {
  success: boolean
  deployments_created: Deployment[]
  requires_name_selection: boolean
  known_stacks?: KnownStack[]
  stack_exists?: boolean
  existing_stack_name?: string
}

// ==================== Scan Compose Dirs Types ====================

/**
 * Request to scan directories for compose files
 */
export interface ScanComposeDirsRequest {
  paths?: string[]
  recursive?: boolean
  max_depth?: number
}

/**
 * Metadata about a discovered compose file
 */
export interface ComposeFileInfo {
  path: string
  project_name: string
  services: string[]
  size: number
  modified: string
}

/**
 * Response from directory scan
 */
export interface ScanComposeDirsResponse {
  success: boolean
  compose_files: ComposeFileInfo[]
  error?: string
}

// ==================== Read Compose File Types ====================

/**
 * Response containing compose file content
 */
export interface ReadComposeFileResponse {
  success: boolean
  path: string
  content?: string
  env_content?: string
  error?: string
}

// ==================== Generate From Containers Types ====================

/**
 * Request to generate compose from running containers
 */
export interface GenerateFromContainersRequest {
  project_name: string
  host_id: string
}

/**
 * Compose preview response (generated from containers)
 */
export interface ComposePreviewResponse {
  compose_yaml: string
  services: string[]
  warnings: string[]
}

/**
 * Running project info (for generate from containers UI)
 */
export interface RunningProject {
  project_name: string
  host_id: string
  host_name: string | null
  container_count: number
  services: string[]
}
