import { useCallback, useEffect, useRef, useState } from 'react'
import type { ColumnSizingState } from '@tanstack/react-table'
import { toast } from 'sonner'
import { useUpdatePreferences, useUserPreferences } from '@/lib/hooks/useUserPreferences'
import { MAX_RESIZABLE_COLUMN_ID_LENGTH } from '../utils/customColumns'

// Mirrors the backend ColumnSizing entry limit (api/v2/user.py) so one unsavable key can't fail the whole map.
const MAX_SIZED_COLUMNS = 100

function sameSizing(a: ColumnSizingState, b: ColumnSizingState): boolean {
  const aKeys = Object.keys(a)
  return aKeys.length === Object.keys(b).length && aKeys.every((key) => a[key] === b[key])
}

/**
 * Container-table column widths, persisted in user preferences.
 *
 * Widths change locally while dragging and are saved once per committed
 * resize. Saves are serialized (only the latest pending map is sent next),
 * and stored preferences are not hydrated over an uncommitted or unsaved
 * local change, so a refetch of an older save cannot undo a newer width.
 */
export function useColumnSizingPreference(columnIds: readonly string[]) {
  const { data: preferences } = useUserPreferences()
  // Own mutation observer: per-call settle handling must not be shared with the table's other preference saves.
  const { mutateAsync: savePreferences } = useUpdatePreferences()
  const stored = preferences?.container_table_column_sizing

  const [columnSizing, setLocalSizing] = useState<ColumnSizingState>(stored ?? {})
  const [isSyncBlocked, setIsSyncBlocked] = useState(false)
  const dirtyRef = useRef(false)
  const savingRef = useRef(false)
  const queuedRef = useRef<ColumnSizingState | null>(null)
  const columnIdsRef = useRef(columnIds)
  columnIdsRef.current = columnIds
  const sizingRef = useRef(columnSizing)
  sizingRef.current = columnSizing

  useEffect(() => {
    if (isSyncBlocked) return
    const next = stored ?? {}
    setLocalSizing((prev) => (sameSizing(prev, next) ? prev : next))
  }, [stored, isSyncBlocked])

  const save = useCallback(
    (sizing: ColumnSizingState) => {
      savingRef.current = true
      savePreferences({ container_table_column_sizing: sizing })
        .catch(() => {
          toast.error('Could not save column widths')
        })
        .finally(() => {
          const queued = queuedRef.current
          queuedRef.current = null
          if (queued) {
            save(queued)
            return
          }
          savingRef.current = false
          if (!dirtyRef.current) setIsSyncBlocked(false)
        })
    },
    [savePreferences],
  )

  const setColumnSizing = useCallback((updater: ColumnSizingState | ((prev: ColumnSizingState) => ColumnSizingState)) => {
    dirtyRef.current = true
    setIsSyncBlocked(true)
    setLocalSizing(updater)
  }, [])

  const commitColumnSizing = useCallback(
    (sizing: ColumnSizingState) => {
      const known = new Set(columnIdsRef.current)
      const pruned = Object.fromEntries(
        Object.entries(sizing)
          .filter(([id]) => known.has(id) && id.length <= MAX_RESIZABLE_COLUMN_ID_LENGTH)
          .slice(0, MAX_SIZED_COLUMNS),
      )
      dirtyRef.current = false
      setIsSyncBlocked(true)
      setLocalSizing(pruned)
      if (savingRef.current) {
        queuedRef.current = pruned
      } else {
        save(pruned)
      }
    },
    [save],
  )

  /** Persist one column's width, or return it to the default width when `width` is null. */
  const commitColumnWidth = useCallback(
    (columnId: string, width: number | null) => {
      const rest = Object.fromEntries(Object.entries(sizingRef.current).filter(([id]) => id !== columnId))
      commitColumnSizing(width === null ? rest : { ...rest, [columnId]: width })
    },
    [commitColumnSizing],
  )

  const resetColumnSizing = useCallback(() => commitColumnSizing({}), [commitColumnSizing])

  return { columnSizing, setColumnSizing, commitColumnWidth, resetColumnSizing }
}
