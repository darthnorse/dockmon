import type { ColumnSizingState } from '@tanstack/react-table'

interface SizedColumn {
  id: string
  getSize: () => number
}

/**
 * CSS grid tracks for the container table. A column the user resized is
 * pinned at its width; the rest keep the default behaviour (small columns
 * fixed, wider ones sharing leftover space).
 */
export function buildGridTemplate(columns: SizedColumn[], sizing: ColumnSizingState): string {
  return columns
    .map((col) => {
      const size = col.getSize()
      if (col.id in sizing || size <= 100) return `${size}px`
      return `minmax(${size}px, 1fr)`
    })
    .join(' ')
}
