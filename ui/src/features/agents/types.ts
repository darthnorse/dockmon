/**
 * Agent Types for DockMon v2.2.0
 *
 * Type definitions for remote agent management
 */

export interface Agent {
  agent_id: string
  host_id: string
  host_name: string | null
  engine_id: string
  version: string
  proto_version: string
  capabilities: AgentCapabilities
  status: 'online' | 'offline' | 'degraded'
  connected: boolean
  last_seen_at: string | null  // ISO timestamp
  registered_at: string | null // ISO timestamp
}

export interface AgentCapabilities {
  stats_collection?: boolean
  container_updates?: boolean
  self_update?: boolean
}

export interface RegistrationTokenResponse {
  success: boolean
  token: string
  expires_at: string  // ISO timestamp
}

export interface AgentListResponse {
  success: boolean
  agents: Agent[]
  total: number
  connected_count: number
}

export interface AgentStatusResponse {
  success: boolean
  agent: Agent
}
