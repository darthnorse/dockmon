/**
 * useDynamicPageSize - Calculate optimal page size based on available viewport height
 *
 * Calculates how many rows can fit in the available space to avoid empty space
 * on large monitors while keeping reasonable limits on small screens.
 */

import { useState, useEffect, useRef } from 'react'

interface UseDynamicPageSizeOptions {
  /** Estimated height of each row in pixels */
  rowHeight?: number
  /** Minimum number of rows to show */
  minRows?: number
  /** Maximum number of rows to show */
  maxRows?: number
  /** Additional space to subtract from available height (for headers, footers, etc.) */
  reservedSpace?: number
}

export function useDynamicPageSize(options: UseDynamicPageSizeOptions = {}) {
  const {
    rowHeight = 60, // Default: ~60px per row (table row with padding)
    minRows = 10,
    maxRows = 100,
    reservedSpace = 300, // Default: ~300px for headers, filters, pagination
  } = options

  const [pageSize, setPageSize] = useState(20) // Default fallback
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let debounceTimer: NodeJS.Timeout | null = null

    const calculatePageSize = () => {
      // Wait for container to be mounted
      if (!containerRef.current) {
        return
      }

      // Get the container element's actual height
      const containerHeight = containerRef.current.clientHeight

      // If container height is too small (not rendered yet), skip
      if (containerHeight < 100) {
        return
      }

      // Calculate how many rows can fit
      const usableHeight = containerHeight - reservedSpace
      const calculatedRows = Math.floor(usableHeight / rowHeight)

      // Clamp to min/max bounds
      const boundedRows = Math.max(minRows, Math.min(maxRows, calculatedRows))

      setPageSize(boundedRows)
    }

    const debouncedCalculate = () => {
      if (debounceTimer) {
        clearTimeout(debounceTimer)
      }
      debounceTimer = setTimeout(calculatePageSize, 150)
    }

    // Calculate initially with a delay to ensure DOM is rendered
    const initialTimeout = setTimeout(calculatePageSize, 200)

    // Recalculate on window resize (debounced)
    const handleResize = () => debouncedCalculate()
    window.addEventListener('resize', handleResize)

    // Also recalculate when container size changes using ResizeObserver (debounced)
    let resizeObserver: ResizeObserver | null = null
    if (containerRef.current) {
      resizeObserver = new ResizeObserver(debouncedCalculate)
      resizeObserver.observe(containerRef.current)
    }

    return () => {
      clearTimeout(initialTimeout)
      if (debounceTimer) clearTimeout(debounceTimer)
      window.removeEventListener('resize', handleResize)
      if (resizeObserver) {
        resizeObserver.disconnect()
      }
    }
  }, [rowHeight, minRows, maxRows, reservedSpace])

  return { pageSize, containerRef }
}
