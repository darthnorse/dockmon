import { useState, useCallback } from 'react'
import type { TimeRange } from './historyTypes'

export const STORAGE_KEY = 'dockmon.statsHistoryRange'

const VALID_RANGES: readonly TimeRange[] = [
  'live', '1h', '8h', '24h', '7d', '30d', '60d', '90d',
]

function isValidRange(v: string | null): v is TimeRange {
  return v !== null && (VALID_RANGES as readonly string[]).includes(v)
}

function readInitial(): TimeRange {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (isValidRange(v)) return v
  } catch {
    // localStorage may be disabled (private mode, strict settings);
    // fall through to the default.
  }
  return 'live'
}

/**
 * Persists the user's selected stats range across modal/drawer opens.
 * Shared across all StatsSection instances via a single localStorage key.
 */
export function useLastSelectedRange(): [TimeRange, (r: TimeRange) => void] {
  const [range, setRangeState] = useState<TimeRange>(readInitial)

  const setRange = useCallback((r: TimeRange) => {
    setRangeState(r)
    try {
      localStorage.setItem(STORAGE_KEY, r)
    } catch {
      // Silent: in-memory state still updates so the UI works for this
      // session even if persistence fails.
    }
  }, [])

  return [range, setRange]
}
