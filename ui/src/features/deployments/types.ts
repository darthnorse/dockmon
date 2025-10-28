/**
 * Deployment Types - v2.1
 *
 * Type definitions for container deployments and templates
 * Matches backend API response structure from deployment v2.1
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
  | 'failed'          // Failed during execution
  | 'rolled_back'     // Failed and rolled back (before commitment point)

/**
 * Deployment type - container or docker-compose stack
 */
export type DeploymentType = 'container' | 'stack'

/**
 * Main deployment object returned by API
 */
export interface Deployment {
  id: string                    // Composite key: {host_id}:{deployment_short_id}
  name: string                  // User-friendly name (unique per host)
  deployment_type: DeploymentType  // 'container' or 'stack' (backend field name)
  status: DeploymentStatus      // Current state in state machine
  host_id: string               // UUID of target Docker host
  host_name?: string            // Optional: host display name

  // Deployment definition (JSON structure)
  definition: DeploymentDefinition | StackDefinition

  // Progress tracking
  progress_percent: number      // 0-100
  current_stage: string | null  // e.g., "pulling", "creating", "starting"
  error_message: string | null  // Error details if status is 'failed'

  // State machine metadata
  committed: boolean            // Whether commitment point was reached
  rollback_on_failure: boolean  // Auto-rollback on deployment failure
  created_by?: string | null    // Username who created deployment (from design spec)

  // Container tracking
  container_ids?: string[]      // SHORT container IDs (12 chars) for running deployments (from deployment_metadata)

  // Timestamps
  created_at: string            // ISO timestamp with 'Z' suffix
  updated_at: string | null     // ISO timestamp with 'Z' suffix, updated on each state change
  started_at?: string | null    // ISO timestamp with 'Z' suffix when deployment execution started
  completed_at: string | null   // ISO timestamp with 'Z' suffix when completed/failed
}

/**
 * Container deployment definition (matches backend SecurityValidator input)
 */
export interface DeploymentDefinition {
  // Stack-specific field (type = 'stack')
  compose_yaml?: string         // Docker Compose YAML content (for stack deployments)

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
 * API request to create a deployment
 */
export interface CreateDeploymentRequest {
  name: string
  type: DeploymentType
  host_id: string
  definition: DeploymentDefinition | StackDefinition
}

/**
 * API request to create a template (matches backend TemplateCreate Pydantic model)
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
