/**
 * Central stats view configuration. View definitions and helpers consumed by
 * StatsCharts and friends. The Go stats-service consumes the same view names
 * for its tier/history queries.
 */

export const VIEWS = [
  { name: '1h' as const, seconds: 3600, label: '1h' },
  { name: '8h' as const, seconds: 28800, label: '8h' },
  { name: '24h' as const, seconds: 86400, label: '24h' },
  { name: '7d' as const, seconds: 604800, label: '7d' },
  { name: '30d' as const, seconds: 2592000, label: '30d' },
  { name: '60d' as const, seconds: 5184000, label: '60d' },
  { name: '90d' as const, seconds: 7776000, label: '90d' },
] as const

export const DEFAULT_POINTS_PER_VIEW = 500

export const LIVE_TIME_WINDOW = 600

export const DEFAULT_HIST_TIME_WINDOW = VIEWS[0].seconds

export function computeInterval(viewSeconds: number, pointsPerView: number, pollingInterval: number = 2): number {
  return Math.max(viewSeconds / pointsPerView, pollingInterval)
}

// NOTE: gap-detection is deliberately NOT implemented here. The earlier draft
// had a `detectGaps()` helper, but with no consumers in this commit it was
// just dead code carrying a latent unit-mismatch footgun (it wanted `t` in
// milliseconds while MiniChart wants unix seconds). It will be reintroduced
// alongside the first real consumer, where the unit contract can be enforced
// end-to-end rather than via a JSDoc warning.
