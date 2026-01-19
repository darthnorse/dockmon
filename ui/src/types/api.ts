/**
 * API Type Definitions
 *
 * NOTE: These are hand-written for v2.0 Phase 2
 * FUTURE: Generate from OpenAPI spec with Orval (when backend adds OpenAPI)
 */

// ==================== Authentication ====================

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  user: {
    id: number
    username: string
    is_first_login: boolean
  }
  message: string
}

export interface CurrentUserResponse {
  user: {
    id: number
    username: string
    display_name?: string | null
    is_first_login?: boolean
  }
}

// ==================== User Preferences ====================

export interface UserPreferences {
  theme: 'dark' | 'light'
  group_by: 'env' | 'region' | 'compose' | 'none' | null
  compact_view: boolean
  collapsed_groups: string[]
}

export interface PreferencesUpdate {
  theme?: 'dark' | 'light'
  group_by?: 'env' | 'region' | 'compose' | 'none'
  compact_view?: boolean
  collapsed_groups?: string[]
}

// ==================== Common ====================

export interface ApiErrorResponse {
  detail: string
}

// ==================== Docker Hosts ====================

export interface Host {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'degraded' | string
  security_status?: 'secure' | 'insecure' | 'unknown' | null
  last_checked: string  // ISO timestamp
  container_count: number
  error?: string | null
  // Organization
  tags?: string[] | null
  description?: string | null
  // System information
  os_type?: string | null
  os_version?: string | null
  kernel_version?: string | null
  docker_version?: string | null
  daemon_started_at?: string | null  // ISO timestamp
  // System resources
  total_memory?: number | null  // Total memory in bytes
  num_cpus?: number | null  // Number of CPUs
  host_ip?: string | null  // Host IP address (for systemd agents only)
  // Podman compatibility (Issue #20)
  is_podman?: boolean  // True if host runs Podman instead of Docker
  // Connection type (v2.2.0)
  connection_type?: 'local' | 'agent' | 'remote'
  agent?: {
    agent_id: string
    engine_id: string
    version: string
    proto_version: number
    capabilities: Record<string, unknown>
    status: string
    connected: boolean
    last_seen_at: string | null  // ISO timestamp
    registered_at: string | null  // ISO timestamp
  } | null
}

// ==================== Containers ====================

export interface Container {
  id: string
  short_id: string
  name: string
  state: 'running' | 'stopped' | 'paused' | 'restarting' | 'removing' | 'exited' | 'created' | 'dead' | string
  status: string
  host_id: string
  host_name: string
  image: string
  created: string  // ISO timestamp
  auto_restart: boolean
  restart_attempts: number
  desired_state?: 'should_run' | 'on_demand' | 'unspecified' | null
  // Docker configuration
  ports?: string[] | null  // e.g., ["8080:80/tcp", "443:443/tcp"]
  restart_policy?: string | null  // e.g., "always", "unless-stopped", "no"
  volumes?: string[] | null  // e.g., ["/var/www:/usr/share/nginx/html"]
  env?: Record<string, string> | null  // Environment variables
  labels?: Record<string, string> | null  // Docker labels
  // Stats from Go stats service
  cpu_percent?: number | null
  memory_usage?: number | null
  memory_limit?: number | null
  memory_percent?: number | null
  network_rx?: number | null
  network_tx?: number | null
  net_bytes_per_sec?: number | null
  disk_read?: number | null
  disk_write?: number | null
  disk_io_per_sec?: number | null
  // Tags
  tags?: string[] | null
  // Docker network IP addresses (GitHub Issue #37)
  docker_ip?: string | null  // Primary Docker network IP
  docker_ips?: Record<string, string> | null  // All network IPs {network_name: ip}
}

// ==================== Docker Images ====================

export interface DockerImage {
  id: string               // 12-char short ID
  tags: string[]           // e.g., ["nginx:latest"]
  size: number             // Size in bytes
  created: string          // ISO timestamp
  in_use: boolean          // Whether any container uses this image
  container_count: number  // Number of containers using this image
  containers: Array<{      // Containers using this image
    id: string
    name: string
  }>
  dangling: boolean        // True if image has no tags
}

// ==================== Docker Networks ====================

export interface DockerNetwork {
  id: string                // 12-char short ID
  name: string              // Network name
  driver: string            // bridge, overlay, host, null, etc.
  scope: string             // local, swarm, global
  created: string           // ISO timestamp
  internal: boolean         // Internal network (no external connectivity)
  containers: Array<{       // Connected containers
    id: string
    name: string
  }>
  container_count: number   // Number of connected containers
  is_builtin: boolean       // True for bridge/host/none
}

// ==================== Docker Volumes ====================

export interface DockerVolume {
  name: string              // Volume name
  driver: string            // Volume driver (local, etc.)
  mountpoint: string        // Mount point on host
  created: string           // ISO timestamp
  containers: Array<{       // Containers using this volume
    id: string
    name: string
  }>
  container_count: number   // Number of containers using this volume
  in_use: boolean           // Whether any container uses this volume
}

// ==================== Registry Credentials ====================

export interface RegistryCredential {
  id: number
  registry_url: string
  username: string
  // password never returned by API for security
  created_at: string
  updated_at: string
}

export interface RegistryCredentialCreate {
  registry_url: string
  username: string
  password: string
}

export interface RegistryCredentialUpdate {
  username?: string
  password?: string
}
