/**
 * Central stats configuration — mirrors backend stats_config.py
 */

export const VIEWS = [
  { name: '1h' as const, seconds: 3600, label: '1h' },
  { name: '8h' as const, seconds: 28800, label: '8h' },
  { name: '24h' as const, seconds: 86400, label: '24h' },
  { name: '7d' as const, seconds: 604800, label: '7d' },
  { name: '30d' as const, seconds: 2592000, label: '30d' },
] as const

export const DEFAULT_POINTS_PER_VIEW = 500

export const LIVE_TIME_WINDOW = 600

export const DEFAULT_HIST_TIME_WINDOW = VIEWS[0].seconds

export function computeInterval(viewSeconds: number, pointsPerView: number, pollingInterval: number = 2): number {
  return Math.max(viewSeconds / pointsPerView, pollingInterval)
}

/**
 * Detect gaps in time-series data and insert null values for uPlot gap rendering.
 * A gap is detected when the timestamp delta exceeds 1.5x the expected interval.
 */
interface GapPoint {
  t: number
  cpu: null
  mem: null
  net_rx: null
}

export function detectGaps<T extends { t: number }>(
  data: T[],
  viewSeconds: number,
): (T | GapPoint)[] {
  if (data.length < 2) return [...data]

  // Coarsest possible interval (ppv minimum = 100) × 2 = real gap threshold
  const threshold = (viewSeconds / 100) * 2 * 1000

  const result: (T | GapPoint)[] = [data[0]!]

  for (let i = 1; i < data.length; i++) {
    const prev = data[i - 1]!
    const curr = data[i]!
    if (curr.t - prev.t > threshold) {
      result.push({
        t: prev.t + threshold / 2,
        cpu: null,
        mem: null,
        net_rx: null,
      })
    }
    result.push(curr)
  }

  return result
}
