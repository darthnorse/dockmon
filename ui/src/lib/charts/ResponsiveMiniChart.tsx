/**
 * ResponsiveMiniChart — auto-sizing wrapper for MiniChart. Measures the parent
 * container width via ResizeObserver (debounced) and forwards the resolved
 * pixel width to MiniChart. Height is caller-supplied; nothing here maintains
 * an aspect ratio.
 */

import { memo, useEffect, useRef, useState } from 'react'
import { MiniChart, MiniChartProps } from './MiniChart'

interface ResponsiveMiniChartProps extends Omit<MiniChartProps, 'width'> {
  /** Minimum width in pixels (default: 60) */
  minWidth?: number
  /** Maximum width in pixels (optional) */
  maxWidth?: number
  /** Debounce delay in ms for resize events (default: 100) */
  debounceMs?: number
}

function ResponsiveMiniChartInner({
  data,
  timestamps,
  color,
  height = 32,
  minWidth = 60,
  maxWidth,
  debounceMs = 100,
  label,
  showAxes,
  timeWindow,
  formatTooltipTime,
}: ResponsiveMiniChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState<number>(minWidth)
  const resizeTimeoutRef = useRef<NodeJS.Timeout>()

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const updateWidth = () => {
      const width = container.clientWidth
      if (width > 0) {
        const clampedWidth = Math.max(
          minWidth,
          maxWidth ? Math.min(width, maxWidth) : width
        )
        setContainerWidth(clampedWidth)
      }
    }

    // Debounced so rapid parent resizes don't thrash uPlot.
    const handleResize = (entries: ResizeObserverEntry[]) => {
      if (resizeTimeoutRef.current) {
        clearTimeout(resizeTimeoutRef.current)
      }
      resizeTimeoutRef.current = setTimeout(() => {
        for (const entry of entries) {
          const width = entry.contentRect.width
          if (width > 0) {
            const clampedWidth = Math.max(
              minWidth,
              maxWidth ? Math.min(width, maxWidth) : width
            )
            setContainerWidth(clampedWidth)
          }
        }
      }, debounceMs)
    }

    const resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(container)
    updateWidth()

    return () => {
      resizeObserver.disconnect()
      if (resizeTimeoutRef.current) {
        clearTimeout(resizeTimeoutRef.current)
      }
    }
  }, [minWidth, maxWidth, debounceMs])

  return (
    <div ref={containerRef} className="w-full">
      <MiniChart
        data={data}
        color={color}
        width={containerWidth}
        height={height}
        timestamps={timestamps}
        showAxes={showAxes}
        label={label}
        timeWindow={timeWindow}
        formatTooltipTime={formatTooltipTime}
      />
    </div>
  )
}

/**
 * Memoized export — paired with the memoized inner `MiniChart` so the hot-path
 * dashboard avoids re-rendering both wrappers on every parent re-render.
 */
export const ResponsiveMiniChart = memo(ResponsiveMiniChartInner)
