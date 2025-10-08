/**
 * Container Types - Phase 3b
 *
 * Type definitions for Docker containers
 * Matches backend API response structure
 */

export interface Container {
  id: string
  name: string
  image: string
  state: 'running' | 'stopped' | 'paused' | 'restarting' | 'removing' | 'dead'
  status: string // e.g., "Up 2 hours", "Exited (0) 5 minutes ago"
  created: string // ISO timestamp
  ports: ContainerPort[]
  labels: Record<string, string>
  host_id?: string
  host_name?: string
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
  block_read: number
  block_write: number
}
