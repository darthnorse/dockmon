/**
 * Shared types for the historical stats feature.
 * The StatsHistoryResponse shape matches the backend Go stats-service
 * HistoryResponse struct (see stats-service/persistence/read.go).
 */

export type TimeRange = 'live' | '1h' | '8h' | '24h' | '7d' | '30d'

export type HistoricalRange = Exclude<TimeRange, 'live'>

/**
 * Response body shape returned by the Python proxy endpoints:
 * - GET /api/hosts/{host_id}/stats/history
 * - GET /api/hosts/{host_id}/containers/{container_id}/stats/history
 *
 * Column-major arrays: each array is parallel to `timestamps`.
 * Nulls in the data arrays represent missing buckets (chart gaps).
 * `memory_used_bytes`, `memory_limit_bytes`, `container_count` are only
 * populated for host-history responses.
 */
export interface StatsHistoryResponse {
  tier: HistoricalRange
  tier_seconds: number
  interval_seconds: number
  from: number
  to: number
  server_time: number
  timestamps: number[]
  cpu: (number | null)[]
  mem: (number | null)[]
  net_bps: (number | null)[]
  memory_used_bytes?: (number | null)[]
  memory_limit_bytes?: (number | null)[]
  container_count?: (number | null)[]
}
