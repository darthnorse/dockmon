/**
 * Deployment Types - v2.2.7
 *
 * Type definitions for stacks and deployments
 * Stacks are filesystem-based compose configurations (v2.2.7+)
 * Deployments reference stacks by name
 */

/**
 * Deployment status values from backend state machine (7-state flow)
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

/**
 * Deployment type - container or docker-compose stack
 * @deprecated v2.2.7+ - All deployments are stacks
 */
export type DeploymentType = 'container' | 'stack'

// ==================== Stack Types (v2.2.7+) ====================

/**
 * Stack from the Stacks API (filesystem-based)
 * GET /api/stacks/{name} returns full content
 * GET /api/stacks returns list without content
 */
export interface Stack {
  name: string                  // Stack name (lowercase alphanumeric, hyphens, underscores)
  deployment_count: number      // Number of deployments using this stack
  compose_yaml?: string         // Docker Compose YAML content (optional in list, present in detail)
  env_content?: string | null   // Optional .env file content
}

/**
 * Stack list item (without content) - for list view performance
 */
export interface StackListItem {
  name: string
  deployment_count: number
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

// ==================== Deployment Types (v2.2.7+) ====================

/**
 * Main deployment object returned by API (v2.2.7+)
 * Deployments reference stacks by name, content is on filesystem
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

/**
 * API request to create a deployment (v2.2.7+)
 * Stack must exist first via POST /api/stacks
 */
export interface CreateDeploymentRequest {
  host_id: string
  stack_name: string            // Must exist in /api/stacks
  rollback_on_failure?: boolean // Default: true
}

/**
 * API request to update a deployment (v2.2.7+)
 */
export interface UpdateDeploymentRequest {
  stack_name?: string           // Change target stack
  host_id?: string              // Change target host
}

/**
 * Container deployment definition (matches backend SecurityValidator input)
 */
export interface DeploymentDefinition {
  // Stack-specific fields (type = 'stack')
  compose_yaml?: string         // Docker Compose YAML content (for stack deployments)
  variables?: Record<string, string>  // Environment variables for ${VAR} substitution in compose YAML

  // Container-specific fields (type = 'container')
  image?: string                // Docker image (e.g., "nginx:latest") - required for containers, not for stacks

  // Optional container configuration
  name?: string                 // Container name override
  command?: string[]            // Override CMD
  entrypoint?: string[]         // Override ENTRYPOINT
  environment?: Record<string, string>  // Environment variables
  ports?: string[]              // Port mappings (e.g., ["8080:80", "443:443"])
  volumes?: string[]            // Volume mounts (e.g., ["/host:/container"])
  labels?: Record<string, string>       // Docker labels

  // Network configuration
  network_mode?: string         // "bridge", "host", "none", or custom network
  hostname?: string             // Container hostname

  // Resource limits
  memory_limit?: string         // e.g., "512m", "1g"
  cpu_limit?: string            // e.g., "0.5", "1.0"

  // Security settings (validated by backend)
  privileged?: boolean          // CRITICAL: Privileged mode (usually blocked)
  cap_add?: string[]            // Add Linux capabilities
  cap_drop?: string[]           // Drop Linux capabilities

  // Restart policy
  restart_policy?: string       // "no", "always", "unless-stopped", "on-failure"

  // Health check
  healthcheck?: {
    test: string[]              // Health check command
    interval?: string           // Check interval (e.g., "30s")
    timeout?: string            // Timeout (e.g., "5s")
    retries?: number            // Number of retries
    start_period?: string       // Start period (e.g., "0s")
  }
}

/**
 * Stack deployment definition (docker-compose structure)
 */
export interface StackDefinition {
  services: Record<string, DeploymentDefinition>  // Service name → config
  networks?: Record<string, unknown>              // Network definitions
  volumes?: Record<string, unknown>               // Volume definitions
}

/**
 * Deployment template for reusable configurations
 * Matches backend API response from template_manager._template_to_dict()
 */
export interface DeploymentTemplate {
  id: string                     // Template ID (tpl_<12chars>)
  name: string                   // Template name (unique)
  category: string | null        // Category (e.g., 'web-servers', 'databases')
  description: string | null     // User-friendly description
  deployment_type: string        // 'container' or 'stack'

  // Template definition with variable placeholders ${VAR_NAME}
  template_definition: DeploymentDefinition | StackDefinition

  // Variable definitions (backend format: dict of var_name -> var_config)
  variables: Record<string, TemplateVariableConfig>

  // System vs user templates
  is_builtin: boolean            // Built-in templates cannot be edited/deleted

  // Timestamps
  created_at: string             // ISO timestamp with 'Z' suffix
  updated_at: string | null      // ISO timestamp with 'Z' suffix
}

/**
 * Template variable configuration (backend format)
 * Used in DeploymentTemplate.variables
 */
export interface TemplateVariableConfig {
  description?: string           // Optional description for users
  default?: string | number      // Optional default value
  required?: boolean             // Whether variable must be provided
  type?: 'string' | 'integer' | 'boolean'  // Variable type
}

/**
 * Rendered template (after variable substitution)
 */
export interface RenderedTemplate {
  definition: DeploymentDefinition | StackDefinition
  missing_variables: string[]   // Variables that weren't provided
}

/**
 * Security validation result from backend
 */
export interface SecurityValidation {
  result: 'allow' | 'warn' | 'block'
  violations: SecurityViolation[]
}

/**
 * Individual security violation
 */
export interface SecurityViolation {
  level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  message: string               // Human-readable error message
  field?: string                // Which field caused the violation
  suggestion?: string           // How to fix it
}

/**
 * Deployment progress event from WebSocket (simple)
 */
export interface DeploymentProgressEvent {
  type: 'deployment_progress'
  data: {
    host_id: string
    entity_id: string           // deployment_id
    progress: number            // 0-100
    stage: string               // "pulling", "creating", "starting", "completed"
    message: string             // Human-readable message
  }
}

/**
 * Layer-by-layer progress from WebSocket (detailed, like updates!)
 */
export interface DeploymentLayerProgressEvent {
  type: 'deployment_layer_progress'
  data: {
    host_id: string
    entity_id: string           // deployment_id
    overall_progress: number    // 0-100
    layers: LayerProgress[]
    total_layers: number
    remaining_layers: number    // Layers not shown (for performance)
    summary: string             // e.g., "Downloading 3 of 8 layers (45%) @ 12.5 MB/s"
    speed_mbps?: number         // Download speed in MB/s
  }
}

/**
 * Individual layer progress
 */
export interface LayerProgress {
  id: string                    // Layer SHA256
  status: 'waiting' | 'downloading' | 'verifying' | 'extracting' | 'complete' | 'cached'
  current: number               // Bytes downloaded
  total: number                 // Total bytes
  percent: number               // 0-100
}

/**
 * Deployment completion event from WebSocket
 */
export interface DeploymentCompletedEvent {
  type: 'deployment_completed'
  data: {
    id: string                  // Composite key
    status: 'completed'
    container_id?: string       // Created container ID (if type=container)
  }
}

/**
 * Deployment failure event from WebSocket
 */
export interface DeploymentFailedEvent {
  type: 'deployment_failed'
  data: {
    id: string
    status: 'failed'
    error_message: string
    committed: boolean          // Whether commitment point was reached
  }
}

/**
 * Deployment rollback event from WebSocket
 */
export interface DeploymentRolledBackEvent {
  type: 'deployment_rolled_back'
  data: {
    id: string
    status: 'rolled_back'
  }
}

/**
 * Deployment creation event from WebSocket
 */
export interface DeploymentCreatedEvent {
  type: 'deployment_created'
  data: Deployment
}

/**
 * Union type for all deployment WebSocket events
 */
export type DeploymentWebSocketEvent =
  | DeploymentCreatedEvent
  | DeploymentProgressEvent
  | DeploymentLayerProgressEvent
  | DeploymentCompletedEvent
  | DeploymentFailedEvent
  | DeploymentRolledBackEvent

/**
 * API request to create a template (matches backend TemplateCreate Pydantic model)
 * @deprecated v2.2.7+ - Use Stacks API instead
 */
export interface CreateTemplateRequest {
  name: string
  deployment_type: string  // 'container' or 'stack'
  template_definition: DeploymentDefinition | StackDefinition
  category?: string | null
  description?: string | null
  variables?: Record<string, TemplateVariableConfig> | null
}

/**
 * API request to update a template (matches backend TemplateUpdate Pydantic model)
 */
export interface UpdateTemplateRequest {
  name?: string | null
  category?: string | null
  description?: string | null
  template_definition?: DeploymentDefinition | StackDefinition | null
  variables?: Record<string, TemplateVariableConfig> | null
}

/**
 * API request to render a template (matches backend TemplateRenderRequest Pydantic model)
 */
export interface RenderTemplateRequest {
  values: Record<string, any>  // Variable name → value (string, number, boolean)
}

/**
 * API query filters for deployments list
 */
export interface DeploymentFilters {
  host_id?: string
  status?: DeploymentStatus
  limit?: number
  offset?: number
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
}

/**
 * API response from import operation
 */
export interface ImportDeploymentResponse {
  success: boolean
  deployments_created: Deployment[]
  requires_name_selection: boolean
  known_stacks?: KnownStack[]
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
 * Request to read a compose file's content
 */
export interface ReadComposeFileRequest {
  path: string
}

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
