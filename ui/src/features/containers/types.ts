/**
 * Container Types - Phase 3b/3d
 *
 * Type definitions for Docker containers
 * Matches backend API response structure
 */

export interface Container {
  id: string
  name: string
  image: string
  state: 'running' | 'stopped' | 'exited' | 'created' | 'paused' | 'restarting' | 'removing' | 'dead'
  status: string // e.g., "Up 2 hours", "Exited (0) 5 minutes ago"
  created: string // ISO timestamp
  ports?: string[] // e.g., ["8080:80/tcp", "443:443/tcp"]
  labels?: Record<string, string>
  tags?: string[] // Phase 3d - Derived from labels (compose:*, swarm:*, custom)
  host_id?: string
  host_name?: string
  // Docker configuration
  volumes?: string[] // e.g., ["/var/www:/usr/share/nginx/html"]
  env?: Record<string, string> // Environment variables
  restart_policy?: string // e.g., "always", "unless-stopped", "no"
  // Policy fields
  auto_restart?: boolean // DockMon's auto-restart feature (not Docker's restart policy)
  desired_state?: 'should_run' | 'on_demand' | 'unspecified' // Expected operational state
  // Stats fields (Phase 3d - from Go stats service)
  cpu_percent?: number
  memory_usage?: number
  memory_limit?: number
  memory_percent?: number
  network_rx?: number
  network_tx?: number
  net_bytes_per_sec?: number // Calculated network rate (bytes/sec)
}

export interface ContainerAction {
  type: 'start' | 'stop' | 'restart' | 'pause' | 'unpause' | 'remove'
  container_id: string
  host_id: string
}

export interface ContainerStats {
  cpu_percent: number
  memory_usage: number
  memory_limit: number
  memory_percent: number
  network_rx: number
  network_tx: number
  net_bytes_per_sec: number // Calculated network rate (bytes/sec)
  block_read: number
  block_write: number
}

export interface ContainerUpdateStatus {
  update_available: boolean
  current_image: string | null
  current_digest: string | null
  latest_image: string | null
  latest_digest: string | null
  floating_tag_mode: 'exact' | 'minor' | 'major' | 'latest'
  last_checked_at: string | null
  auto_update_enabled?: boolean
}

export interface ContainerHttpHealthCheck {
  // Configuration
  enabled: boolean
  url: string
  method: string
  expected_status_codes: string
  timeout_seconds: number
  check_interval_seconds: number
  follow_redirects: boolean
  verify_ssl: boolean
  headers_json: string | null
  auth_config_json: string | null

  // State tracking
  current_status: 'unknown' | 'healthy' | 'unhealthy'
  last_checked_at: string | null
  last_success_at: string | null
  last_failure_at: string | null
  consecutive_successes: number | null  // null = no health check record exists
  consecutive_failures: number | null   // null = no health check record exists
  last_response_time_ms: number | null
  last_error_message: string | null

  // Auto-restart integration
  auto_restart_on_failure: boolean
  failure_threshold: number
  success_threshold: number
}
