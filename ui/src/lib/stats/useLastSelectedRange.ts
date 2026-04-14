import { useState, useEffect, useCallback } from 'react'
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

// Module-level pub/sub so every mounted useLastSelectedRange consumer stays
// in sync within a single tab. (The browser `storage` event only fires on
// *other* tabs, not the one that wrote the value, so we need our own
// in-tab broadcaster in addition to the cross-tab listener below.)
type Listener = (r: TimeRange) => void
const listeners = new Set<Listener>()

function broadcast(r: TimeRange) {
  for (const fn of listeners) fn(r)
}

/**
 * Persists the user's selected stats range across modal/drawer opens and
 * keeps every live instance (container modal + host drawer + etc.) in sync.
 *
 * Sync mechanics:
 * - Writes go through the module-level broadcaster, so all mounted hooks
 *   update in the same React render cycle.
 * - A `storage` event listener picks up changes made in *other* browser tabs.
 * - Default is `'live'`. Invalid or unreadable storage falls back silently.
 */
export function useLastSelectedRange(): [TimeRange, (r: TimeRange) => void] {
  const [range, setRangeState] = useState<TimeRange>(readInitial)

  useEffect(() => {
    // In-tab sync: react to writes from any other hook instance.
    const onBroadcast: Listener = (r) => setRangeState(r)
    listeners.add(onBroadcast)

    // Cross-tab sync: react to localStorage writes from another tab.
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY) return
      if (isValidRange(e.newValue)) setRangeState(e.newValue)
    }
    window.addEventListener('storage', onStorage)

    return () => {
      listeners.delete(onBroadcast)
      window.removeEventListener('storage', onStorage)
    }
  }, [])

  const setRange = useCallback((r: TimeRange) => {
    try {
      localStorage.setItem(STORAGE_KEY, r)
    } catch {
      // Silent: in-memory broadcast still happens so the UI works for this
      // session even if persistence fails.
    }
    broadcast(r)
  }, [])

  return [range, setRange]
}
