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
  ports: ContainerPort[]
  labels: Record<string, string>
  tags?: string[] // Phase 3d - Derived from labels (compose:*, swarm:*, custom)
  host_id?: string
  host_name?: string
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

export interface ContainerPort {
  ip?: string
  private_port: number
  public_port?: number
  type: 'tcp' | 'udp'
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
