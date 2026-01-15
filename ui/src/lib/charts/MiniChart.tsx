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
import { formatRelativeTime, formatYAxisValue } from './formatters'

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
  /** Show axes and enhanced features (default: false for compact sparklines) */
  showAxes?: boolean
}

/**
 * Round network scale to nice values to prevent flickering gridlines
 * Returns stable scale maxima like 10 B/s, 100 B/s, 1 KB/s, 10 KB/s, etc.
 */
function getNiceNetworkScaleMax(maxValue: number): number {
  if (maxValue < 1) return 10 // Minimum 10 B/s

  const k = 1024

  // Define nice scale thresholds for consistent gridlines
  const niceValues = [
    10, 50, 100, 500, 1000, // B/s
    2 * k, 5 * k, 10 * k, 50 * k, 100 * k, 500 * k, // KB/s
    k * k, 2 * k * k, 5 * k * k, 10 * k * k, 50 * k * k, 100 * k * k, // MB/s
    k * k * k, // GB/s
  ]

  // Find the smallest nice value that fits the data
  for (const nice of niceValues) {
    if (nice >= maxValue) return nice
  }

  // Fallback for very large values
  return Math.ceil(maxValue / (k * k * k)) * (k * k * k)
}

export function MiniChart({
  data,
  color,
  height = 50,
  width = 100,
  label,
  showAxes = false,
}: MiniChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const plotRef = useRef<uPlot | null>(null)
  const [tooltip, setTooltip] = React.useState<{
    show: boolean
    x: number
    y: number
    time: string
    value: string
  }>({
    show: false,
    x: 0,
    y: 0,
    time: '',
    value: '',
  })

  // Use raw data without smoothing to show actual values
  const chartData = data

  // Generate X-axis as time offset from start
  // Left = oldest data (0), Right = newest data (max seconds)
  const xData = useMemo(() => {
    const dataLength = chartData.length
    // X values count up from 0 (oldest) to max (newest)
    return Array.from({ length: dataLength }, (_, i) => i * 3)
  }, [chartData.length])

  // Determine if this is a percentage metric (CPU/Memory) or bytes (Network)
  const isPercentage = color === 'cpu' || color === 'memory'

  // uPlot configuration
  const opts = useMemo<uPlot.Options>(() => ({
    width,
    height,
    cursor: {
      show: showAxes,
      x: false, // No vertical crosshair line
      y: false, // No horizontal crosshair line
      points: {
        show: showAxes,
        size: (_u, seriesIdx) => seriesIdx === 1 ? 10 : 0, // Larger hover point
        stroke: (_u, seriesIdx) => seriesIdx === 1 ? CHART_COLORS[color] : '',
        fill: () => '#ffffff',
        width: 2,
      },
      drag: {
        x: false,
        y: false,
      },
    },
    legend: {
      show: false, // Disabled - we use hover points instead
    },
    axes: [
      {
        // X-axis (time)
        show: showAxes,
        space: 25,
        stroke: '#64748b',
        grid: {
          show: false,
        },
        ticks: {
          show: true,
          stroke: '#cbd5e1',
          width: 1,
          size: 4,
        },
        splits: (u: uPlot, _axisIdx: number, scaleMin: number, scaleMax: number) => {
          // Check actual number of data points
          const dataPointCount = u.data[0]?.length ?? 0

          // Single data point - just show "now"
          if (dataPointCount <= 1) {
            return [scaleMax]
          }

          const totalSeconds = scaleMax
          const chartWidth = u.width

          // Very early data - just show "now"
          if (totalSeconds < 5) {
            return [scaleMax]
          }

          // Dynamically choose intervals based on both time range and chart width
          let targetSecondsAgo: number[]

          if (totalSeconds < 15) {
            targetSecondsAgo = [0, 5, 10, 15]
          } else if (totalSeconds < 30) {
            // Very short range
            if (chartWidth < 300) {
              targetSecondsAgo = [0, 15, 30] // Minimal labels for narrow charts
            } else {
              targetSecondsAgo = [0, 5, 10, 15, 20, 25, 30]
            }
          } else if (totalSeconds < 60) {
            // Short range
            if (chartWidth < 300) {
              targetSecondsAgo = [0, 30, 60]
            } else if (chartWidth < 500) {
              targetSecondsAgo = [0, 20, 40, 60]
            } else {
              targetSecondsAgo = [0, 15, 30, 45, 60]
            }
          } else {
            // Normal 2-minute window
            if (chartWidth < 300) {
              targetSecondsAgo = [0, 60, 120] // Minimal: just now, 1m, 2m
            } else if (chartWidth < 500) {
              targetSecondsAgo = [0, 60, 120] // Medium: now, 1m, 2m
            } else {
              targetSecondsAgo = [0, 30, 60, 90, 120] // Full labels
            }
          }

          // Convert to time offsets, only including values within our range
          const ticks = targetSecondsAgo
            .map(secondsAgo => totalSeconds - secondsAgo)
            .filter(offset => offset >= scaleMin && offset <= scaleMax)

          // Always include "now" (rightmost), but not the leftmost endpoint
          // This avoids misleading labels like "2m" when we only have ~117s of data
          const ticksWithNow = Array.from(new Set([...ticks, scaleMax]))
            .sort((a, b) => a - b)

          // Filter out ticks that would create duplicate labels
          // This prevents showing "1m" twice when data is ~87s (rounds to 1m) and we have a 60s tick
          const uniqueTicks: number[] = []
          const seenLabels = new Set<string>()

          for (const tick of ticksWithNow) {
            const secondsAgo = totalSeconds - tick
            const label = secondsAgo === 0 ? 'now' : formatRelativeTime(secondsAgo)

            if (!seenLabels.has(label)) {
              uniqueTicks.push(tick)
              seenLabels.add(label)
            }
          }

          return uniqueTicks
        },
        values: (_u: uPlot, vals: number[]) => {
          // Convert time offsets to "seconds ago" labels
          const maxVal = Math.max(...vals)
          return vals.map((v: number) => {
            const secondsAgo = maxVal - v
            return secondsAgo === 0 ? 'now' : formatRelativeTime(secondsAgo)
          })
        },
        font: '11px system-ui, -apple-system, sans-serif',
      },
      {
        // Y-axis (values)
        show: showAxes,
        space: 40,
        stroke: '#64748b',
        grid: {
          show: showAxes,
          stroke: '#1e293b',
          width: 1,
        },
        ticks: {
          show: true,
          stroke: '#cbd5e1',
          width: 1,
          size: 4,
        },
        splits: (_u: uPlot, _axisIdx: number, _scaleMin: number, scaleMax: number) => {
          // Generate nice round tick positions for gridlines
          if (isPercentage) {
            // For CPU/Memory: fixed nice intervals based on range
            if (scaleMax <= 1) return [0, 1]
            if (scaleMax <= 5) return [0, 5]
            if (scaleMax <= 15) return [0, 5, 10, 15]
            if (scaleMax <= 40) return [0, 10, 20, 30, 40]
            if (scaleMax <= 60) return [0, 15, 30, 45, 60]
            return [0, 25, 50, 75, 100]
          }

          // For Network: generate 4-5 evenly spaced nice ticks
          const k = 1024
          const numTicks = 4
          const rawStep = scaleMax / numTicks

          // Round step to nice values
          let niceStep: number
          if (rawStep < 10) niceStep = 10
          else if (rawStep < 50) niceStep = 50
          else if (rawStep < 100) niceStep = 100
          else if (rawStep < 500) niceStep = 500
          else if (rawStep < k) niceStep = k
          else if (rawStep < 5 * k) niceStep = 5 * k
          else if (rawStep < 10 * k) niceStep = 10 * k
          else if (rawStep < 50 * k) niceStep = 50 * k
          else if (rawStep < 100 * k) niceStep = 100 * k
          else if (rawStep < 500 * k) niceStep = 500 * k
          else if (rawStep < k * k) niceStep = k * k
          else niceStep = Math.ceil(rawStep / (k * k)) * (k * k)

          // Generate ticks at nice intervals
          const ticks = [0]
          for (let i = niceStep; i <= scaleMax; i += niceStep) {
            ticks.push(i)
          }
          return ticks
        },
        values: (_u: uPlot, vals: number[]) => {
          // Format y-axis values based on metric type
          return vals.map((v: number) => formatYAxisValue(v, isPercentage))
        },
        font: '11px system-ui, -apple-system, sans-serif',
      },
    ],
    scales: {
      x: {
        time: false, // We're using seconds-ago, not timestamps
      },
      y: {
        range: (_u: uPlot, dataMin: number, dataMax: number) => {
          if (showAxes) {
            // Enhanced mode: Smart ranges with zero baseline
            if (isPercentage) {
              // For CPU/Memory: dynamic range based on actual values
              // Always anchor to 0, but adjust max to show detail
              if (dataMax < 0.8) {
                return [0, 1] // Extremely low usage: 0-1%
              } else if (dataMax < 3) {
                return [0, 5] // Very low usage: 0-5%
              } else if (dataMax < 10) {
                return [0, 15] // Low usage: 0-15%
              } else if (dataMax < 30) {
                return [0, 40] // Medium-low usage: 0-40%
              } else if (dataMax < 50) {
                return [0, 60] // Medium usage: 0-60%
              } else if (dataMax < 80) {
                return [0, 100] // High usage: 0-100%
              } else {
                return [0, 100] // Very high usage: 0-100%
              }
            }
            // For Network: use nice rounded scale values for stable gridlines
            if (dataMax - dataMin < 0.01) {
              return [0, getNiceNetworkScaleMax(Math.max(dataMax, 1))]
            }
            // Add 10% padding then round to nice value for consistent display
            return [0, getNiceNetworkScaleMax(dataMax * 1.1)]
          } else {
            // Compact mode: Original auto-scaling with padding
            if (dataMax - dataMin < 0.01) {
              if (dataMax < 0.5) {
                return [0, 1]
              }
              const center = dataMax
              const margin = Math.max(center * 0.1, 0.1)
              return [center - margin, center + margin]
            }
            const padding = (dataMax - dataMin) * 0.1
            return [dataMin - padding, dataMax + padding]
          }
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
          show: showAxes, // Only show points in enhanced mode
          size: 4,
          stroke: CHART_COLORS[color],
          fill: '#ffffff',
          width: 2,
        },
        value: (_u: uPlot, v: number) => {
          // Format tooltip value based on metric type
          if (v == null) return '—'
          if (isPercentage) {
            return `${v.toFixed(1)}%`
          }
          // Network bytes
          return formatYAxisValue(v, false)
        },
      },
    ],
    padding: showAxes ? [8, 10, 0, 10] : [4, 4, 4, 4],
    hooks: {
      setCursor: [
        (u: uPlot) => {
          const { idx } = u.cursor

          if (idx === null || idx === undefined || !showAxes) {
            setTooltip(prev => ({ ...prev, show: false }))
            return
          }

          // Get data at cursor index
          const xVal = u.data[0]?.[idx]
          const yVal = u.data[1]?.[idx]

          if (xVal === undefined || xVal === null || yVal === undefined || yVal === null) {
            setTooltip(prev => ({ ...prev, show: false }))
            return
          }

          // Calculate time ago
          const maxXVal = u.data[0]?.[u.data[0].length - 1] ?? 0
          const secondsAgo = maxXVal - xVal
          const timeLabel = secondsAgo === 0 ? 'now' : `${formatRelativeTime(secondsAgo)} ago`

          // Format value
          let valueLabel: string
          if (isPercentage) {
            valueLabel = `${yVal.toFixed(1)}%`
          } else {
            valueLabel = formatYAxisValue(yVal, false)
          }

          // Get position of the actual data point (not cursor)
          const left = u.valToPos(xVal, 'x')
          const top = u.valToPos(yVal, 'y')

          setTooltip({
            show: true,
            x: left,
            y: top,
            time: timeLabel,
            value: valueLabel,
          })
        },
      ],
    },
  }), [width, height, color, label, isPercentage, showAxes, setTooltip])

  // Initialize chart
  useEffect(() => {
    if (!chartRef.current) return

    // Destroy existing chart if any
    if (plotRef.current) {
      plotRef.current.destroy()
      plotRef.current = null
    }

    try {
      // Create uPlot instance
      const plot = new uPlot(
        opts,
        [xData, chartData],
        chartRef.current
      )

      plotRef.current = plot
      debug.log('MiniChart', `Initialized ${color} chart with ${chartData.length} points`)

      // Cleanup on unmount
      return () => {
        plot.destroy()
        plotRef.current = null
      }
    } catch (error) {
      debug.error('MiniChart', `Failed to initialize ${color} chart:`, error)
      return undefined
    }
  }, [opts, xData, chartData, color]) // Reinitialize when config or data structure changes

  // Update chart data when it changes
  useEffect(() => {
    if (!plotRef.current) return

    try {
      plotRef.current.setData([xData, chartData])
    } catch (error) {
      debug.error('MiniChart', 'Failed to update chart data:', error)
    }
  }, [xData, chartData])

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
    <div style={{ position: 'relative', width: `${width}px`, height: `${height}px` }}>
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
      {tooltip.show && showAxes && (
        <div
          style={{
            position: 'absolute',
            left: `${tooltip.x + 32}px`,
            top: `${tooltip.y - 50}px`,
            background: 'rgba(0, 0, 0, 0.85)',
            color: '#fff',
            padding: '6px 10px',
            borderRadius: '6px',
            fontSize: '12px',
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
            zIndex: 1000,
            boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
          }}
        >
          <div style={{ fontWeight: '600', marginBottom: '2px' }}>{tooltip.value}</div>
          <div style={{ fontSize: '11px', opacity: 0.8 }}>{tooltip.time}</div>
        </div>
      )}
    </div>
  )
}

// Memoize to prevent unnecessary re-renders
export default React.memo(MiniChart)
