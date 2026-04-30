/**
 * Virtualized container table.
 *
 * Two scroll modes:
 *   - Window scroll (default): for full-page lists like /containers, where
 *     the page itself scrolls. Sticky header sticks to the viewport.
 *   - Element scroll (opt-in via `scrollElement`): for embedded contexts
 *     like the host modal, where the page can't scroll (modal is
 *     fixed-positioned, body overflow hidden) and an inner element handles
 *     scrolling instead.
 *
 * The virtualizer must be wired to whichever element actually scrolls; a
 * window-scroll virtualizer never sees scroll events inside a modal and
 * leaves the body of the list unreachable.
 */

import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { flexRender, Column, Table as ReactTable } from '@tanstack/react-table'
import { useVirtualizer, useWindowVirtualizer, Virtualizer } from '@tanstack/react-virtual'

import type { Container } from '../types'

function alignClass(column: Column<Container>, fallback = ''): string {
  return column.columnDef.meta?.align === 'center' ? 'text-center' : fallback
}

interface VirtualizedTableProps {
  table: ReactTable<Container>
  /**
   * The element with `overflow: auto`/`scroll` that owns the scroll, or
   * undefined to use window scroll. `null` means element-scroll mode is
   * selected but the ref hasn't attached yet — the virtualizer will
   * render no items until it becomes non-null.
   */
  scrollElement?: HTMLElement | null | undefined
}

const ESTIMATED_ROW_HEIGHT_PX = 56

export function VirtualizedTable({ table, scrollElement }: VirtualizedTableProps) {
  if (scrollElement !== undefined) {
    return <ElementScrollVirtualizedTable table={table} scrollElement={scrollElement} />
  }
  return <WindowScrollVirtualizedTable table={table} />
}

function WindowScrollVirtualizedTable({ table }: { table: ReactTable<Container> }) {
  const rows = table.getRowModel().rows
  const containerRef = useRef<HTMLDivElement>(null)

  // useWindowVirtualizer needs the table's offset from the document top so
  // its viewport math accounts for the page header/filters above it.
  const [scrollMargin, setScrollMargin] = useState(0)
  useLayoutEffect(() => {
    if (!containerRef.current) return
    const update = () => {
      if (!containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      setScrollMargin(rect.top + window.scrollY)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(containerRef.current)
    // Observe document.body so layout shifts above the table (banners
    // toggling, modals expanding the page) re-measure scrollMargin.
    // ResizeObserver on the table alone misses these — siblings change
    // the table's position without changing its size.
    observer.observe(document.body)
    window.addEventListener('resize', update)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [])

  // Key measurements by row.id (not array index) so a row's measured height
  // stays attached to its identity. Without this, sorting reshuffles indices
  // and the virtualizer applies stale per-index heights to whichever row
  // landed at that index, producing the visible row-overlap bug.
  const getItemKey = useCallback((index: number) => rows[index]?.id ?? index, [rows])

  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => ESTIMATED_ROW_HEIGHT_PX,
    overscan: 8,
    scrollMargin,
    getItemKey,
  })

  return <VirtualizedTableShell table={table} virtualizer={virtualizer} containerRef={containerRef} />
}

function ElementScrollVirtualizedTable({
  table,
  scrollElement,
}: {
  table: ReactTable<Container>
  scrollElement: HTMLElement | null
}) {
  const rows = table.getRowModel().rows
  const containerRef = useRef<HTMLDivElement>(null)

  // Track the table's offset within the scroll element. Without this,
  // scrolling reveals a blank gap between the sticky header and the
  // first row equal to the offset of content above the table.
  const [scrollMargin, setScrollMargin] = useState(0)
  useLayoutEffect(() => {
    if (!containerRef.current || !scrollElement) return
    const update = () => {
      if (!containerRef.current || !scrollElement) return
      const containerRect = containerRef.current.getBoundingClientRect()
      const scrollRect = scrollElement.getBoundingClientRect()
      setScrollMargin(containerRect.top - scrollRect.top + scrollElement.scrollTop)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(containerRef.current)
    observer.observe(scrollElement)
    return () => observer.disconnect()
  }, [scrollElement])

  // The inline `() => scrollElement` is load-bearing. TanStack Virtual
  // re-evaluates getScrollElement on every render, so the eventual
  // non-null element from the callback ref in HostContainersTab gets
  // picked up automatically. Wrapping this in `useCallback([], )` would
  // freeze it at the initial null value and the virtualizer would never
  // attach scroll listeners.
  // getItemKey: see WindowScrollVirtualizedTable for rationale.
  const getItemKey = useCallback((index: number) => rows[index]?.id ?? index, [rows])

  const virtualizer = useVirtualizer({
    count: rows.length,
    estimateSize: () => ESTIMATED_ROW_HEIGHT_PX,
    overscan: 8,
    getScrollElement: () => scrollElement,
    scrollMargin,
    getItemKey,
  })

  return <VirtualizedTableShell table={table} virtualizer={virtualizer} containerRef={containerRef} />
}

type TableVirtualizer = Virtualizer<Window, Element> | Virtualizer<HTMLElement, Element>

function VirtualizedTableShell({
  table,
  virtualizer,
  containerRef,
}: {
  table: ReactTable<Container>
  virtualizer: TableVirtualizer
  containerRef: React.RefObject<HTMLDivElement>
}) {
  const rows = table.getRowModel().rows

  // Row heights are kept in sync with content via:
  //  - `ref={virtualizer.measureElement}` on each row (ResizeObserver-driven
  //    measurement of actual rendered height — handles tag chips wrapping,
  //    multi-line names, font-load reflows, etc.)
  //  - `getItemKey: (i) => rows[i].id` on the virtualizer (set in the parent
  //    components above), which keys the measurement cache by row identity
  //    so sort/filter doesn't apply a stale index's height to a different
  //    row at that index.
  // Together these handle dynamic content sizes without manual cache
  // invalidation. Earlier versions tried to invalidate on order change via
  // `virtualizer.measure()`; that was working around the index-keyed cache
  // rather than fixing it.

  // min-w-0 on each cell lets long content shrink below intrinsic width.
  const gridTemplate = table.getVisibleLeafColumns()
    .map((col) => {
      const size = col.getSize()
      return size <= 100 ? `${size}px` : `minmax(${size}px, 1fr)`
    })
    .join(' ')

  const rowBaseStyle = useMemo(
    () => ({
      gridTemplateColumns: gridTemplate,
      position: 'absolute' as const,
      top: 0,
      left: 0,
      width: '100%' as const,
    }),
    [gridTemplate],
  )

  const virtualItems = virtualizer.getVirtualItems()
  // TanStack offsets vRow.start by scrollMargin; subtract to translate
  // within the rowgroup.
  const scrollMargin = virtualizer.options.scrollMargin

  return (
    <div
      ref={containerRef}
      role="table"
      className="rounded-lg border border-border overflow-x-auto"
      data-testid="containers-table"
    >
      <div className="bg-muted/50 sticky top-0 z-10 border-b border-border" role="rowgroup">
        {table.getHeaderGroups().map((headerGroup) => (
          <div
            key={headerGroup.id}
            role="row"
            className="grid"
            style={{ gridTemplateColumns: gridTemplate }}
          >
            {headerGroup.headers.map((header) => (
              <div
                key={header.id}
                role="columnheader"
                className={`px-4 py-3 text-sm font-medium min-w-0 ${alignClass(header.column, 'text-left')}`}
              >
                {header.isPlaceholder
                  ? null
                  : flexRender(header.column.columnDef.header, header.getContext())}
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Body — empty state lives outside the absolute-positioned wrapper
          because getTotalSize() is 0 with no rows, which would otherwise
          collapse the message to height 0. */}
      {rows.length === 0 ? (
        <div role="rowgroup">
          <div role="row">
            <div role="cell" className="px-4 py-8 text-center text-sm text-muted-foreground">
              No containers found
            </div>
          </div>
        </div>
      ) : (
        <div role="rowgroup" style={{ position: 'relative', height: virtualizer.getTotalSize() }}>
          {virtualItems.map((vRow) => {
            const row = rows[vRow.index]
            if (!row) return null
            return (
              <div
                key={row.id}
                role="row"
                data-index={vRow.index}
                ref={virtualizer.measureElement}
                className="grid border-t hover:bg-[#151827] transition-colors"
                style={{
                  ...rowBaseStyle,
                  transform: `translateY(${vRow.start - scrollMargin}px)`,
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <div
                    key={cell.id}
                    role="cell"
                    className={`px-4 py-3 min-w-0 ${alignClass(cell.column)}`}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
