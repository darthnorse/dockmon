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
 * `memory_used_bytes` and `memory_limit_bytes` are optional companion columns
 * for richer memory labels; `container_count` is host-only.
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

/**
 * Response body shape returned by the on-demand live endpoints:
 * - GET /api/hosts/{host_id}/stats/live
 * - GET /api/hosts/{host_id}/containers/{container_id}/stats/live
 *
 * The EXTENDED in-memory sparkline for ONE entity: column-major arrays all
 * parallel to `timestamps` (unix seconds). `net` is bytes/sec; `mem` is percent;
 * the memory byte columns carry absolute snapshots for byte labels. Distinct
 * from the lean broadcast sparkline (cpu/mem/net only, index mode).
 */
export interface LiveStatsResponse {
  timestamps: number[]
  cpu: (number | null)[]
  mem: (number | null)[]
  net: (number | null)[]
  memory_used_bytes: (number | null)[]
  memory_limit_bytes: (number | null)[]
}
