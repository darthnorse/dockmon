/**
 * Custom column ID convention for the container table (Issue #207).
 *
 * Built-in columns: bare IDs ("name", "state", "cpu", ...).
 * Custom columns:   "env:<varname>" or "label:<labelname>".
 *
 * The column ID is the source of truth — TanStack Table uses it as the
 * column key, user prefs store visibility/order keyed on it, and the cell
 * renderer uses parseColumnId to dispatch on kind.
 */

export type ColumnIdParsed =
  | { kind: 'env' | 'label'; name: string }
  | { kind: 'builtin'; name: string }

export function parseColumnId(id: string): ColumnIdParsed {
  if (id.startsWith('env:')) {
    return { kind: 'env', name: id.slice(4) }
  }
  if (id.startsWith('label:')) {
    return { kind: 'label', name: id.slice(6) }
  }
  return { kind: 'builtin', name: id }
}

export function isCustomColumnId(id: string): boolean {
  return id.startsWith('env:') || id.startsWith('label:')
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
