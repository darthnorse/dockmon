/**
 * MiniChart Component - High-performance sparkline using uPlot
 *
 * FEATURES:
 * - Hardware-accelerated canvas rendering
 * - EMA smoothing (α=0.3) to reduce jitter
 * - Supports CPU (amber), Memory (blue), Network (green)
 * - 80-100px wide × 40-50px tall
 * - Renders up to 40 data points (2 minutes at 3s avg interval)
 *
 * PERFORMANCE:
 * - ~40KB bundle size (uPlot)
 * - < 16ms render time (60 FPS)
 * - Minimal re-renders via React.memo
 *
 * USAGE:
 * ```tsx
 * <MiniChart
 *   data={[12.3, 15.6, 18.2, ...]}
 *   color="cpu"     // 'cpu' | 'memory' | 'network'
 *   height={50}
 *   width={100}
 * />
 * ```
 */

import React, { useEffect, useRef, useMemo } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { debug } from '@/lib/debug'

// Color palette matching design system
const CHART_COLORS = {
  cpu: '#F59E0B',     // Amber
  memory: '#3B82F6',  // Blue
  network: '#22C55E', // Green
} as const

type ChartColor = keyof typeof CHART_COLORS

export interface MiniChartProps {
  /** Array of data points (max 40) */
  data: number[]
  /** Chart color theme */
  color: ChartColor
  /** Chart height in pixels */
  height?: number
  /** Chart width in pixels */
  width?: number
  /** Optional label for accessibility */
  label?: string
}

/**
 * Apply Exponential Moving Average smoothing to reduce jitter
 * Formula: smoothed = α * current + (1 - α) * previous
 * α = 0.3 provides good balance between responsiveness and smoothness
 */
function applyEMASmoothing(data: number[], alpha: number = 0.3): number[] {
  if (data.length === 0) return []

  const first = data[0]
  if (first === undefined) return []

  const smoothed: number[] = [first]

  for (let i = 1; i < data.length; i++) {
    const current = data[i]
    const previous = smoothed[i - 1]
    if (current !== undefined && previous !== undefined) {
      smoothed[i] = alpha * current + (1 - alpha) * previous
    }
  }

  return smoothed
}

export function MiniChart({
  data,
  color,
  height = 50,
  width = 100,
  label,
}: MiniChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const plotRef = useRef<uPlot | null>(null)

  // Apply EMA smoothing to data
  const smoothedData = useMemo(() => {
    if (data.length === 0) return []
    return applyEMASmoothing(data)
  }, [data])

  // Generate X-axis indices (0, 1, 2, ...)
  const xData = useMemo(() => {
    return Array.from({ length: smoothedData.length }, (_, i) => i)
  }, [smoothedData.length])

  // uPlot configuration
  const opts = useMemo<uPlot.Options>(() => ({
    width,
    height,
    cursor: {
      show: false,
    },
    legend: {
      show: false,
    },
    axes: [
      {
        // X-axis (hidden)
        show: false,
      },
      {
        // Y-axis (hidden)
        show: false,
      },
    ],
    scales: {
      x: {
        time: false,
      },
      y: {
        auto: true,
        range: (_u, dataMin, dataMax) => {
          // If all values are the same (or very close), use a fixed range
          if (dataMax - dataMin < 0.01) {
            // For values near zero, show 0-1 range
            if (dataMax < 0.5) {
              return [0, 1]
            }
            // For other values, show ±10% around the value
            const center = dataMax
            const margin = Math.max(center * 0.1, 0.1)
            return [center - margin, center + margin]
          }
          // Add 10% padding for visual breathing room
          const padding = (dataMax - dataMin) * 0.1
          return [dataMin - padding, dataMax + padding]
        },
      },
    },
    series: [
      {
        // X-axis data series
        label: 'Time',
      },
      {
        // Y-axis data series
        label: label || 'Value',
        stroke: CHART_COLORS[color],
        width: 2,
        points: {
          show: true,
          size: 4,
          stroke: CHART_COLORS[color],
          fill: '#ffffff',
          width: 2,
        },
      },
    ],
    padding: [4, 4, 4, 4],
  }), [width, height, color, label])

  // Initialize chart
  useEffect(() => {
    if (!chartRef.current) return

    try {
      // Create uPlot instance
      const plot = new uPlot(
        opts,
        [xData, smoothedData],
        chartRef.current
      )

      plotRef.current = plot
      debug.log('MiniChart', `Initialized ${color} chart with ${smoothedData.length} points`)

      // Cleanup on unmount
      return () => {
        plot.destroy()
        plotRef.current = null
      }
    } catch (error) {
      debug.error('MiniChart', 'Failed to initialize chart:', error)
      return undefined
    }
  }, []) // Only run once on mount

  // Update chart data when it changes
  useEffect(() => {
    if (!plotRef.current) return

    try {
      plotRef.current.setData([xData, smoothedData])
    } catch (error) {
      debug.error('MiniChart', 'Failed to update chart data:', error)
    }
  }, [xData, smoothedData])

  // Handle resize
  useEffect(() => {
    if (!plotRef.current) return

    try {
      plotRef.current.setSize({ width, height })
    } catch (error) {
      debug.error('MiniChart', 'Failed to resize chart:', error)
    }
  }, [width, height])

  return (
    <div
      ref={chartRef}
      className="mini-chart"
      role="img"
      aria-label={label || `${color} chart`}
      style={{
        width: `${width}px`,
        height: `${height}px`,
      }}
    />
  )
}

// Memoize to prevent unnecessary re-renders
export default React.memo(MiniChart)
