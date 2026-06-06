/**
 * Custom column ID convention for the container table.
 *
 * Built-in columns use bare IDs ("name", "state", "cpu", ...).
 * Custom columns use "env:<varname>" or "label:<labelname>" with a non-empty
 * name part. The ID is the source of truth — TanStack Table uses it as the
 * column key, user prefs store visibility/order keyed on it, and the cell
 * renderer dispatches on kind via parseColumnId.
 */
import type { ColumnDef } from '@tanstack/react-table'

export type ColumnIdParsed =
  | { kind: 'env' | 'label'; name: string }
  | { kind: 'builtin'; name: string }

export function parseColumnId(id: string): ColumnIdParsed {
  if (id.startsWith('env:') && id.length > 4) {
    return { kind: 'env', name: id.slice(4) }
  }
  if (id.startsWith('label:') && id.length > 6) {
    return { kind: 'label', name: id.slice(6) }
  }
  return { kind: 'builtin', name: id }
}

export function isCustomColumnId(id: string): boolean {
  return parseColumnId(id).kind !== 'builtin'
}

export function getColumnLabel(id: string): string {
  const parsed = parseColumnId(id)
  if (parsed.kind === 'env') return `ENV: ${parsed.name}`
  if (parsed.kind === 'label') return `LABEL: ${parsed.name}`
  return id // built-in IDs: caller should map via COLUMN_LABELS
}

interface ContainerLike {
  env?: Record<string, string> | null
  labels?: Record<string, string> | null
}

/**
 * Returns the value to display in a custom column cell.
 * Returns null for built-in column IDs (caller handles those separately).
 * Returns "" for custom columns whose key is missing.
 */
export function extractColumnValue(
  container: ContainerLike,
  columnId: string,
): string | null {
  const parsed = parseColumnId(columnId)
  if (parsed.kind === 'builtin') return null
  const source = parsed.kind === 'env' ? container.env : container.labels
  return source?.[parsed.name] ?? ''
}

/**
 * Build a TanStack column def for a custom env/label column.
 * Pure function — safe to call from useMemo without dep tracking.
 *
 * Cell rendering truncates with ellipsis on overflow (env values are
 * frequently long URLs that would otherwise bleed into the next column)
 * and exposes the full value on hover via the title attribute.
 */
export function buildCustomColumnDef<T extends ContainerLike>(
  columnId: string,
): ColumnDef<T> {
  return {
    id: columnId,
    header: getColumnLabel(columnId),
    accessorFn: (row) => extractColumnValue(row, columnId) ?? '',
    cell: (info) => {
      const value = info.getValue() as string
      if (!value) return <span className="text-muted-foreground">—</span>
      return (
        <span className="block truncate" title={value}>
          {value}
        </span>
      )
    },
    enableSorting: true,
    meta: { align: 'left' },
  }
}
