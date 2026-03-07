/**
 * MiniChart Component - High-performance sparkline using uPlot
 *
 * Two modes determined by props:
 * - Compact (no showAxes): tiny sparkline, index-based X, no interaction
 * - Full (showAxes + timestamps + timeWindow): absolute-time X-axis, tooltip, fixed window
 */

import React, { useEffect, useRef, useMemo } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { debug } from '@/lib/debug'
import { formatYAxisValue } from './formatters'

const CHART_COLORS = {
  cpu: '#F59E0B',
  memory: '#3B82F6',
  network: '#22C55E',
} as const

type ChartColor = keyof typeof CHART_COLORS

export interface MiniChartProps {
  data: (number | null)[]
  timestamps?: number[] | undefined
  color: ChartColor
  height?: number
  width?: number
  label?: string | undefined
  showAxes?: boolean | undefined
  timeWindow?: number | undefined
}

function getNiceNetworkScaleMax(maxValue: number): number {
  if (maxValue < 1) return 10
  const k = 1024
  const niceValues = [
    10, 50, 100, 500, 1000,
    2 * k, 5 * k, 10 * k, 50 * k, 100 * k, 500 * k,
    k * k, 2 * k * k, 5 * k * k, 10 * k * k, 50 * k * k, 100 * k * k,
    k * k * k,
  ]
  for (const nice of niceValues) {
    if (nice >= maxValue) return nice
  }
  return Math.ceil(maxValue / (k * k * k)) * (k * k * k)
}

export function MiniChart({
  data,
  timestamps,
  color,
  height = 50,
  width = 100,
  label,
  showAxes = false,
  timeWindow,
}: MiniChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const plotRef = useRef<uPlot | null>(null)
  const [tooltip, setTooltip] = React.useState<{
    show: boolean; x: number; y: number; time: string; value: string
  }>({ show: false, x: 0, y: 0, time: '', value: '' })

  const hasTimestamps = !!(timestamps && timestamps.length > 0)

  const xData = useMemo(() => {
    if (hasTimestamps) return timestamps!
    return Array.from({ length: data.length }, (_, i) => i)
  }, [timestamps, hasTimestamps, data.length])

  const isPercentage = color === 'cpu' || color === 'memory'

  const opts = useMemo<uPlot.Options>(() => ({
    width,
    height,
    cursor: {
      show: showAxes,
      x: false,
      y: false,
      points: {
        show: showAxes,
        size: (_u, seriesIdx) => seriesIdx === 1 ? 10 : 0,
        stroke: (_u, seriesIdx) => seriesIdx === 1 ? CHART_COLORS[color] : '',
        fill: () => '#ffffff',
        width: 2,
      },
      drag: { x: false, y: false },
    },
    legend: { show: false },
    axes: [
      {
        show: showAxes,
        space: 60,
        stroke: '#64748b',
        grid: { show: showAxes, stroke: '#1e293b44', width: 1 },
        ticks: { show: showAxes, stroke: '#cbd5e1', width: 1, size: 4 },
        font: '11px system-ui, -apple-system, sans-serif',
      },
      {
        show: showAxes,
        space: 40,
        stroke: '#64748b',
        grid: { show: showAxes, stroke: '#1e293b', width: 1 },
        ticks: { show: true, stroke: '#cbd5e1', width: 1, size: 4 },
        splits: (_u: uPlot, _axisIdx: number, _scaleMin: number, scaleMax: number) => {
          if (isPercentage) {
            if (scaleMax <= 1) return [0, 1]
            if (scaleMax <= 5) return [0, 5]
            if (scaleMax <= 15) return [0, 5, 10, 15]
            if (scaleMax <= 40) return [0, 10, 20, 30, 40]
            if (scaleMax <= 60) return [0, 15, 30, 45, 60]
            const step = scaleMax <= 100 ? 25 : 50
            const ticks = []
            for (let i = 0; i <= scaleMax; i += step) ticks.push(i)
            return ticks
          }
          const k = 1024
          const rawStep = scaleMax / 4
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
          const ticks = [0]
          for (let i = niceStep; i <= scaleMax; i += niceStep) ticks.push(i)
          return ticks
        },
        values: (_u: uPlot, vals: number[]) =>
          vals.map((v: number) => formatYAxisValue(v, isPercentage)),
        font: '11px system-ui, -apple-system, sans-serif',
      },
    ],
    scales: {
      x: {
        time: hasTimestamps,
        range: (_u: uPlot, dataMin: number, dataMax: number): uPlot.Range.MinMax => {
          if (timeWindow) {
            const now = Date.now() / 1000
            return [now - timeWindow, now]
          }
          return [dataMin, dataMax]
        },
      },
      y: {
        range: (_u: uPlot, dataMin: number, dataMax: number) => {
          if (showAxes) {
            if (isPercentage) {
              if (dataMax < 0.8) return [0, 1]
              if (dataMax < 3) return [0, 5]
              if (dataMax < 10) return [0, 15]
              if (dataMax < 30) return [0, 40]
              if (dataMax < 50) return [0, 60]
              if (dataMax < 80) return [0, 100]
              return [0, Math.ceil(dataMax / 50) * 50]
            }
            if (dataMax - dataMin < 0.01) {
              return [0, getNiceNetworkScaleMax(Math.max(dataMax, 1))]
            }
            return [0, getNiceNetworkScaleMax(dataMax * 1.1)]
          }
          if (dataMax - dataMin < 0.01) {
            if (dataMax < 0.5) return [0, 1]
            const center = dataMax
            const margin = Math.max(center * 0.1, 0.1)
            return [center - margin, center + margin]
          }
          const padding = (dataMax - dataMin) * 0.1
          return [dataMin - padding, dataMax + padding]
        },
      },
    },
    series: [
      { label: 'Time' },
      {
        label: label || 'Value',
        stroke: CHART_COLORS[color],
        width: 2,
        spanGaps: false,
        points: { show: false },
        value: (_u: uPlot, v: number) => {
          if (v == null) return '—'
          return isPercentage ? `${v.toFixed(1)}%` : formatYAxisValue(v, false)
        },
      },
    ],
    padding: showAxes ? [8, 10, 0, 10] : [4, 4, 4, 4],
    hooks: {
      setCursor: [
        (u: uPlot) => {
          const { idx } = u.cursor
          if (idx == null || !showAxes) {
            setTooltip(prev => ({ ...prev, show: false }))
            return
          }
          const xVal = u.data[0]?.[idx]
          const yVal = u.data[1]?.[idx]
          if (xVal == null || yVal == null) {
            setTooltip(prev => ({ ...prev, show: false }))
            return
          }
          const d = new Date(xVal * 1000)
          const timeLabel = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          const valueLabel = isPercentage ? `${yVal.toFixed(1)}%` : formatYAxisValue(yVal, false)
          setTooltip({
            show: true,
            x: u.valToPos(xVal, 'x'),
            y: u.valToPos(yVal, 'y'),
            time: timeLabel,
            value: valueLabel,
          })
        },
      ],
    },
  }), [width, height, color, label, isPercentage, hasTimestamps, showAxes, timeWindow, setTooltip])

  useEffect(() => {
    if (!chartRef.current) return
    if (plotRef.current) {
      plotRef.current.destroy()
      plotRef.current = null
    }
    try {
      const plot = new uPlot(opts, [xData, data], chartRef.current)
      plotRef.current = plot
      debug.log('MiniChart', `Initialized ${color} chart with ${data.length} points`)
      return () => { plot.destroy(); plotRef.current = null }
    } catch (error) {
      debug.error('MiniChart', `Failed to initialize ${color} chart:`, error)
      return undefined
    }
  }, [opts, color, data.length > 0])

  useEffect(() => {
    if (!plotRef.current) return
    try { plotRef.current.setData([xData, data]) }
    catch (error) { debug.error('MiniChart', 'Failed to update chart data:', error) }
  }, [xData, data])

  useEffect(() => {
    if (!plotRef.current) return
    try { plotRef.current.setSize({ width, height }) }
    catch (error) { debug.error('MiniChart', 'Failed to resize chart:', error) }
  }, [width, height])

  return (
    <div style={{ position: 'relative', width: `${width}px`, height: `${height}px` }}>
      <div
        ref={chartRef}
        className="mini-chart"
        role="img"
        aria-label={label || `${color} chart`}
        style={{ width: `${width}px`, height: `${height}px` }}
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

export default React.memo(MiniChart)
