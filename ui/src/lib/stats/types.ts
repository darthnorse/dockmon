/**
 * Stats Type Definitions
 * Centralized types for real-time statistics system
 */

export interface HostMetrics {
  cpu_percent: number
  mem_percent: number
  mem_bytes: number
  net_bytes_per_sec: number
}

export interface Sparklines {
  cpu: number[]
  mem: number[]
  net: number[]
}

export interface ContainerStats {
  id: string
  short_id: string
  name: string
  state: string
  status: string
  host_id: string
  host_name: string
  image: string
  created: string
  auto_restart: boolean
  restart_attempts: number
  cpu_percent: number | null
  memory_usage: number | null
  memory_limit: number | null
  memory_percent: number | null
  network_rx: number | null
  network_tx: number | null
  disk_read: number | null
  disk_write: number | null
}

/**
 * WebSocket message format for containers_update
 */
export interface ContainersUpdateMessage {
  type: 'containers_update'
  data: {
    containers: ContainerStats[]
    hosts: Array<{
      id: string
      name: string
      url: string
      status: string
      [key: string]: unknown
    }>
    host_metrics?: Record<string, HostMetrics>
    host_sparklines?: Record<string, Sparklines>
    timestamp: string
  }
}
