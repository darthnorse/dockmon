/**
 * ResponsiveMiniChart - Auto-sizing wrapper for MiniChart
 *
 * FEATURES:
 * - Automatically fills parent container width
 * - Uses ResizeObserver for responsive updates
 * - Maintains aspect ratio
 * - Optimized with debouncing to prevent excessive re-renders
 *
 * USAGE:
 * ```tsx
 * <div className="flex-1">
 *   <ResponsiveMiniChart
 *     data={sparklineData}
 *     color="cpu"
 *     height={32}
 *   />
 * </div>
 * ```
 */

import { useEffect, useRef, useState } from 'react'
import { MiniChart, MiniChartProps } from './MiniChart'

interface ResponsiveMiniChartProps extends Omit<MiniChartProps, 'width'> {
  /** Minimum width in pixels (default: 60) */
  minWidth?: number
  /** Maximum width in pixels (optional) */
  maxWidth?: number
  /** Debounce delay in ms for resize events (default: 100) */
  debounceMs?: number
}

export function ResponsiveMiniChart({
  data,
  color,
  height = 32,
  minWidth = 60,
  maxWidth,
  debounceMs = 100,
  label,
  showAxes,
}: ResponsiveMiniChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState<number>(minWidth)
  const resizeTimeoutRef = useRef<NodeJS.Timeout>()

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    // Initial measurement
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

    // Debounced resize handler
    const handleResize = (entries: ResizeObserverEntry[]) => {
      // Clear previous timeout
      if (resizeTimeoutRef.current) {
        clearTimeout(resizeTimeoutRef.current)
      }

      // Debounce the update
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

    // Set up ResizeObserver
    const resizeObserver = new ResizeObserver(handleResize)
    resizeObserver.observe(container)

    // Initial measurement
    updateWidth()

    // Cleanup
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
        {...(showAxes !== undefined && { showAxes })}
        {...(label && { label })}
      />
    </div>
  )
}
