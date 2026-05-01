/**
 * WebUI URL Mapping Section (Issue #207).
 *
 * Admin-only editor for the global webui_url_mapping_chain. Users can add,
 * remove, and reorder template strings. The first template that resolves to
 * a non-empty value (when evaluated against a container's env and labels)
 * wins. Templates support ${env:NAME} and ${label:NAME} placeholders.
 *
 * State model: server is canonical; local rows mirror it as
 * `{ id, value }[]` keyed by a synthetic UUID so reorder/remove during
 * mid-edit doesn't lose focus. All updates use functional setRows and a
 * mirror ref so async handlers never close over stale render snapshots.
 * Persist filters out empty/whitespace rows to satisfy the Pydantic
 * validator (which rejects empties), and snapshots/reverts on error so the
 * UI never silently diverges from the server.
 *
 * The parent SystemSettings component wraps everything in a fieldset that
 * disables the form for users without the settings.manage capability, so
 * we don't need to handle disabled state here.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  DndContext,
  closestCenter,
  type DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  verticalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Plus, Trash2, GripVertical } from 'lucide-react'
import { toast } from 'sonner'
import { useGlobalSettings, useUpdateGlobalSettings } from '@/hooks/useSettings'
import { useDndSensors } from '@/features/dashboard/hooks/useDndSensors'

type Row = { id: string; value: string }

function makeRow(value: string): Row {
  return { id: crypto.randomUUID(), value }
}

function rowsEqual(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false
  }
  return true
}

function SortableRow({
  id,
  index,
  value,
  onChange,
  onBlur,
  onRemove,
}: {
  id: string
  index: number
  value: string
  onChange: (next: string) => void
  onBlur: () => void
  onRemove: () => void
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div ref={setNodeRef} style={style} className="flex items-center gap-2">
      <button
        type="button"
        {...attributes}
        {...listeners}
        title="Drag to reorder"
        className="cursor-grab active:cursor-grabbing p-1 text-gray-400 hover:text-white"
      >
        <GripVertical className="h-4 w-4" />
      </button>
      <span className="text-xs text-gray-500 w-6 text-right">{index + 1}.</span>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={onBlur}
        placeholder="https://${env:VIRTUAL_HOST}"
        className="flex-1 rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      />
      <button
        type="button"
        onClick={onRemove}
        title="Remove"
        className="p-2 text-gray-400 hover:text-red-400"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  )
}

export function WebUIUrlMappingSection() {
  const { data: settings } = useGlobalSettings()
  const updateSettings = useUpdateGlobalSettings()
  const sensors = useDndSensors()

  const [rows, setRowsState] = useState<Row[] | null>(null)
  const rowsRef = useRef<Row[] | null>(null)

  // Single setter that keeps state and ref in sync. Accepts either a value or
  // a functional updater. Using a ref means async handlers (persist, drag-end)
  // always read the latest rows without closing over a render snapshot.
  const setRows = useCallback((next: Row[] | ((prev: Row[]) => Row[])) => {
    setRowsState((prev) => {
      const prevRows = prev ?? []
      const resolved = typeof next === 'function' ? next(prevRows) : next
      rowsRef.current = resolved
      return resolved
    })
  }, [])

  // Initial seed from server. We intentionally only seed once (rows === null)
  // to avoid clobbering in-flight typing every time the settings query
  // refetches after a mutation. After the first seed, the server is reflected
  // back into rows only via the optimistic-update path in `persist`.
  useEffect(() => {
    if (rowsRef.current === null && settings) {
      const seeded = (settings.webui_url_mapping_chain ?? []).map(makeRow)
      rowsRef.current = seeded
      setRowsState(seeded)
    }
  }, [settings])

  const persist = useCallback(
    async (nextRows: Row[]) => {
      const snapshot = rowsRef.current
      // Filter empties/whitespace — Pydantic rejects them with 422.
      const payload = nextRows
        .map((r) => r.value.trim())
        .filter((v) => v.length > 0)

      // No-op if payload matches what's already on the server.
      const serverChain = settings?.webui_url_mapping_chain ?? []
      if (rowsEqual(payload, serverChain)) return

      try {
        await updateSettings.mutateAsync({ webui_url_mapping_chain: payload })
      } catch {
        toast.error('Failed to update WebUI URL mapping')
        // Revert local state to the snapshot taken before the mutation.
        if (snapshot) {
          rowsRef.current = snapshot
          setRowsState(snapshot)
        }
      }
    },
    [settings, updateSettings],
  )

  const handleAdd = useCallback(() => {
    // Adding a row is local-only (empty rows aren't persisted). The user
    // types into the new row and persistence happens on blur.
    setRows((prev) => [...prev, makeRow('')])
  }, [setRows])

  const handleChange = useCallback(
    (id: string, value: string) => {
      setRows((prev) => prev.map((r) => (r.id === id ? { ...r, value } : r)))
    },
    [setRows],
  )

  const handleBlur = useCallback(
    (id: string) => {
      const current = rowsRef.current ?? []
      const row = current.find((r) => r.id === id)
      if (!row) return
      // Persist only if this row's trimmed value differs from what's on the
      // server at its current (post-filter) position. Easiest correct check:
      // run the same filter and compare to server. persist() already no-ops
      // when payload matches server, so just call it.
      void persist(current)
    },
    [persist],
  )

  const handleRemove = useCallback(
    (id: string) => {
      setRows((prev) => prev.filter((r) => r.id !== id))
      void persist(rowsRef.current ?? [])
    },
    [persist, setRows],
  )

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event
      if (!over || active.id === over.id) return
      const current = rowsRef.current ?? []
      const oldIndex = current.findIndex((r) => r.id === active.id)
      const newIndex = current.findIndex((r) => r.id === over.id)
      if (oldIndex < 0 || newIndex < 0) return
      const next = arrayMove(current, oldIndex, newIndex)
      setRows(next)
      void persist(next)
    },
    [persist, setRows],
  )

  const displayRows = rows ?? []

  return (
    <div>
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-white">WebUI URL auto-mapping</h3>
        <p className="text-xs text-gray-400 mt-1">
          When a container has no manually-set WebUI URL, DockMon evaluates these
          templates in order against its environment variables and Docker labels.
          The first template that resolves to a non-empty URL is used. Manually-set
          URLs always take precedence.
        </p>
        <p className="text-xs text-gray-500 mt-2">
          Placeholders: <code className="text-gray-300">{'${env:NAME}'}</code> for env vars,{' '}
          <code className="text-gray-300">{'${label:NAME}'}</code> for Docker labels. Example:{' '}
          <code className="text-gray-300">{'https://${env:VIRTUAL_HOST}'}</code>
        </p>
        <p className="text-xs text-gray-500 mt-2">
          Note: <code className="text-gray-300">env:</code> placeholders only resolve for hosts
          using local/mTLS connections; use <code className="text-gray-300">label:</code> for
          agent hosts.
        </p>
      </div>

      {displayRows.length === 0 && (
        <p className="text-sm text-gray-500 italic">
          No templates configured. Auto-mapping is disabled.
        </p>
      )}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={displayRows.map((r) => r.id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-2">
            {displayRows.map((row, index) => (
              <SortableRow
                key={row.id}
                id={row.id}
                index={index}
                value={row.value}
                onChange={(next) => handleChange(row.id, next)}
                onBlur={() => handleBlur(row.id)}
                onRemove={() => handleRemove(row.id)}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>

      <button
        type="button"
        onClick={handleAdd}
        className="mt-3 inline-flex items-center gap-2 rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700"
      >
        <Plus className="h-3.5 w-3.5" />
        Add template
      </button>
    </div>
  )
}
