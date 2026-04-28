/**
 * Virtualized container table body. Uses TanStack Virtual's window-scroll
 * virtualizer so the page-level scroll model is preserved (no inner scroll
 * container, sticky thead still sticks to the viewport).
 *
 * Layout: <table> -> display:grid; rows are display:grid with a shared
 * gridTemplateColumns derived from each column's getSize(). Body rows are
 * absolutely positioned with translateY so only the visible window mounts.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { flexRender, Table as ReactTable } from '@tanstack/react-table'
import { useWindowVirtualizer } from '@tanstack/react-virtual'

import type { Container } from '../types'

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

  // Reset virtualizer state when the row set changes (filter, sort).
  // Without this, scroll position can land on virtualized rows that no
  // longer exist after a filter narrows the result.
  useEffect(() => {
    virtualizer.measure()
  }, [rows, virtualizer])

  // Small columns (≤100px) get fixed widths; larger ones flex with a
  // minimum so the layout never collapses when the viewport is narrow.
  // min-w-0 on each cell lets long content shrink below intrinsic width.
  const gridTemplate = table.getVisibleLeafColumns()
    .map((col) => {
      const size = col.getSize()
      return size <= 100 ? `${size}px` : `minmax(${size}px, 1fr)`
    })
    .join(' ')

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
                className={`px-4 py-3 text-sm font-medium min-w-0 ${
                  header.column.columnDef.meta?.align === 'center' ? 'text-center' : 'text-left'
                }`}
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
                  gridTemplateColumns: gridTemplate,
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${vRow.start - virtualizer.options.scrollMargin}px)`,
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <div
                    key={cell.id}
                    role="cell"
                    className={`px-4 py-3 min-w-0 ${
                      cell.column.columnDef.meta?.align === 'center' ? 'text-center' : ''
                    }`}
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
