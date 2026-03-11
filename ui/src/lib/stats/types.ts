/**
 * Stats Type Definitions
 * Centralized types for real-time statistics system
 */

import type { Container } from '@/features/containers/types'

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

/**
 * ContainerStats narrows Container for WebSocket data where these fields
 * are always present (backend sends full Container.dict() every 2s).
 */
export interface ContainerStats extends Container {
  short_id: string
  host_id: string
  host_name: string
  auto_restart: boolean
  restart_attempts: number
  cpu_percent: number | null
  memory_usage: number | null
  memory_limit: number | null
  memory_percent: number | null
  network_rx: number | null
  network_tx: number | null
  net_bytes_per_sec: number | null
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
    container_sparklines?: Record<string, Sparklines>  // key format: "host_id:container_id"
    timestamp: string
  }
}
