/**
 * Virtualized container table. Uses window-scroll virtualization so the
 * page-level scroll model is preserved (no inner scroll container, the
 * sticky header still sticks to the viewport).
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { flexRender, Column, Table as ReactTable } from '@tanstack/react-table'
import { useWindowVirtualizer } from '@tanstack/react-virtual'

import type { Container } from '../types'

function alignClass(column: Column<Container>, fallback = ''): string {
  return column.columnDef.meta?.align === 'center' ? 'text-center' : fallback
}

interface VirtualizedTableProps {
  table: ReactTable<Container>
}

const ESTIMATED_ROW_HEIGHT_PX = 56

export function VirtualizedTable({ table }: VirtualizedTableProps) {
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

  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => ESTIMATED_ROW_HEIGHT_PX,
    overscan: 8,
    scrollMargin,
  })

  // TanStack Virtual caches measured heights by index, not by row identity,
  // so after a sort, index N can hold a different Container with a different
  // height (the tags column wraps) and laying out against the old cached
  // height causes visible row overlap. Per-row measureElement handles
  // content-driven height changes within a single row, but it doesn't fire
  // when an existing keyed element just gets a new data-index — so we have
  // to invalidate explicitly when ordering changes. Cheap signature catches
  // length changes (filter add/remove) and first/middle/last id changes
  // (sort) without paying an O(n) string-join on every WebSocket stats
  // update (which fires every couple of seconds and otherwise doesn't
  // change row identity at any index).
  const orderSignature = rows.length === 0
    ? ''
    : `${rows.length}|${rows[0]!.id}|${rows[rows.length >> 1]!.id}|${rows[rows.length - 1]!.id}`
  const prevOrderSignatureRef = useRef('')
  useEffect(() => {
    if (prevOrderSignatureRef.current && prevOrderSignatureRef.current !== orderSignature) {
      virtualizer.measure()
    }
    prevOrderSignatureRef.current = orderSignature
  }, [orderSignature, virtualizer])

  // Small columns (≤100px) get fixed widths; larger ones flex with a
  // minimum so the layout never collapses when the viewport is narrow.
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

  return (
    <div
      ref={containerRef}
      role="table"
      className="rounded-lg border border-border overflow-x-auto"
      data-testid="containers-table"
    >
      {/* Header */}
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
                  transform: `translateY(${vRow.start - virtualizer.options.scrollMargin}px)`,
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
