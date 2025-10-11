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
  }
}

// ==================== User Preferences ====================

export interface UserPreferences {
  theme: 'dark' | 'light'
  group_by: 'env' | 'region' | 'compose' | 'none' | null
  compact_view: boolean
  collapsed_groups: string[]
  filter_defaults: Record<string, unknown>
}

export interface PreferencesUpdate {
  theme?: 'dark' | 'light'
  group_by?: 'env' | 'region' | 'compose' | 'none'
  compact_view?: boolean
  collapsed_groups?: string[]
  filter_defaults?: Record<string, unknown>
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
}
