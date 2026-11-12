import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { KeyboardEvent, PointerEvent as ReactPointerEvent } from 'react'

interface ColumnResizeHandleProps {
  label: string
  size: number
  minSize: number
  maxSize: number
  /** Live width while dragging; not persisted. */
  onResize: (width: number) => void
  /** Final width to persist, or null to return the column to its default width. */
  onCommit: (width: number | null) => void
}

const KEYBOARD_STEP_PX = 10

/**
 * Drag handle on a header cell's right edge. Widths start from the cell's
 * rendered width rather than TanStack's getResizeHandler(), which starts
 * from column.getSize() and would snap a flexible (1fr) column narrower.
 */
export function ColumnResizeHandle({ label, size, minSize, maxSize, onResize, onCommit }: ColumnResizeHandleProps) {
  const ref = useRef<HTMLDivElement>(null)
  const stopTrackingRef = useRef<(() => void) | null>(null)
  const [isResizing, setIsResizing] = useState(false)
  const [measuredWidth, setMeasuredWidth] = useState<number | null>(null)

  useEffect(() => () => stopTrackingRef.current?.(), [])

  // A flexible (1fr) column renders wider than its nominal size; report what is on screen.
  useLayoutEffect(() => {
    const cell = ref.current?.parentElement
    if (!cell) return
    const observer = new ResizeObserver(([entry]) => {
      const width = entry?.borderBoxSize?.[0]?.inlineSize
      if (width !== undefined) setMeasuredWidth(Math.round(width))
    })
    observer.observe(cell, { box: 'border-box' })
    return () => observer.disconnect()
  }, [])

  const clamp = (width: number) => Math.min(maxSize, Math.max(minSize, Math.round(width)))
  const renderedWidth = () => ref.current?.parentElement?.getBoundingClientRect().width ?? size

  const handlePointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    stopTrackingRef.current?.()

    const startX = e.clientX
    const startWidth = renderedWidth()
    let lastWidth: number | null = null

    const onMove = (ev: PointerEvent) => {
      // A release outside the window can skip pointerup; the next move then arrives with no button held.
      if ((ev.buttons & 1) === 0) {
        onEnd()
        return
      }
      lastWidth = clamp(startWidth + ev.clientX - startX)
      onResize(lastWidth)
    }
    const onEnd = () => {
      stop()
      if (lastWidth !== null) onCommit(lastWidth)
    }
    const stop = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onEnd)
      window.removeEventListener('pointercancel', onEnd)
      window.removeEventListener('blur', onEnd)
      stopTrackingRef.current = null
      setIsResizing(false)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onEnd)
    window.addEventListener('pointercancel', onEnd)
    window.addEventListener('blur', onEnd)
    stopTrackingRef.current = stop
    setIsResizing(true)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.key === 'ArrowRight' ? KEYBOARD_STEP_PX : e.key === 'ArrowLeft' ? -KEYBOARD_STEP_PX : 0
    if (step === 0) return
    e.preventDefault()
    const width = clamp(renderedWidth() + step)
    onResize(width)
    onCommit(width)
  }

  return (
    <div
      ref={ref}
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={`Resize ${label} column`}
      aria-valuenow={measuredWidth ?? Math.round(size)}
      aria-valuemin={minSize}
      aria-valuemax={maxSize}
      title="Drag to resize, double-click to reset"
      onPointerDown={handlePointerDown}
      onDoubleClick={() => onCommit(null)}
      onKeyDown={handleKeyDown}
      onClick={(e) => e.stopPropagation()}
      className="group/resize absolute right-0 top-0 z-10 flex h-full w-3 cursor-col-resize touch-none select-none justify-center focus-visible:outline-none"
    >
      <div
        className={`h-full w-px transition-colors ${
          isResizing ? 'bg-primary' : 'bg-border group-hover/resize:bg-primary group-focus-visible/resize:bg-primary'
        }`}
      />
    </div>
  )
}
