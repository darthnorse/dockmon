import { formatBytes } from '@/lib/utils/formatting'

/**
 * Shared helpers for the column-major stats series used by both the live and
 * historical charts. Kept in one place so the chart summary (StatsCharts) and
 * the card header (StatsSection) can never disagree on how a value is derived.
 */

/** Index of the last non-null/undefined entry, or -1 if there is none. */
export function latestNonNullIndex(arr: (number | null)[] | undefined): number {
  if (!arr) return -1
  for (let i = arr.length - 1; i >= 0; i--) {
    const v = arr[i]
    if (v !== null && v !== undefined) return i
  }
  return -1
}

/** Value of the last non-null/undefined entry, or undefined if there is none. */
export function latestNonNull(arr: (number | null)[] | undefined): number | undefined {
  if (!arr) return undefined
  const i = latestNonNullIndex(arr)
  return i < 0 ? undefined : (arr[i] as number)
}

/**
 * "<pct>% (<used> / <limit>)" memory summary, built from the latest bucket
 * where mem% is non-null and reading used/limit from that SAME index. Reading
 * one index keeps the three numbers describing a single moment — otherwise a
 * container whose memory_limit was reconfigured mid-window could mix buckets
 * and render a nonsensical ratio (e.g. used > limit). Returns the bare percent
 * when byte columns are absent (the live case), or undefined when there is no
 * data at all.
 */
export function formatMemorySummary(
  mem: (number | null)[],
  memoryUsed: (number | null)[] | undefined,
  memoryLimit: (number | null)[] | undefined,
): string | undefined {
  const i = latestNonNullIndex(mem)
  if (i < 0) return undefined

  const pct = mem[i]
  if (pct == null) return undefined

  const pctStr = `${Math.round(pct * 10) / 10}%`
  const used = memoryUsed?.[i]
  const limit = memoryLimit?.[i]

  if (used != null && limit != null && limit > 0) {
    return `${pctStr} (${formatBytes(used)} / ${formatBytes(limit)})`
  }
  if (used != null) {
    return `${pctStr} (${formatBytes(used)})`
  }
  return pctStr
}
