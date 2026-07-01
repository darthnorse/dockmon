import { useCallback, useEffect, useRef } from 'react'
import { Cpu, MemoryStick, Network } from 'lucide-react'
import { ResponsiveMiniChart } from './ResponsiveMiniChart'
import { CHART_COLORS } from './MiniChart'
import { formatTime } from '@/lib/utils/timeFormat'
import { useTimeFormat } from '@/lib/hooks/useUserPreferences'
import { formatBytes } from '@/lib/utils/formatting'
import { latestNonNull, formatMemorySummary } from '@/lib/stats/columnUtils'

interface StatsChartsProps {
  cpu: (number | null)[]
  mem: (number | null)[]
  net: (number | null)[]
  memoryUsed?: (number | null)[] | undefined
  memoryLimit?: (number | null)[] | undefined
  timestamps: number[]
  timeWindow: number
  cpuValue?: string | undefined
  memValue?: string | undefined
  netValue?: string | undefined
  footer?: string | undefined
}

const CHART_HEIGHT = 120

const CHARTS = [
  { key: 'cpu', label: 'CPU Usage', color: 'cpu', Icon: Cpu },
  { key: 'mem', label: 'Memory Usage', color: 'memory', Icon: MemoryStick },
  { key: 'net', label: 'Network I/O', color: 'network', Icon: Network },
] as const

export function StatsCharts({
  cpu, mem, net, memoryUsed, memoryLimit, timestamps, timeWindow,
  cpuValue, memValue, netValue, footer,
}: StatsChartsProps) {
  const { timeFormat } = useTimeFormat()
  // Stable reference so MiniChart's opts memo doesn't rebuild every render.
  const formatTooltipTime = useCallback(
    (unixSec: number) => formatTime(unixSec * 1000, timeFormat),
    [timeFormat]
  )

  const dataMap = { cpu, mem, net }
  const memoryUsedRef = useRef(memoryUsed)
  const memoryLimitRef = useRef(memoryLimit)

  useEffect(() => {
    memoryUsedRef.current = memoryUsed
    memoryLimitRef.current = memoryLimit
  }, [memoryLimit, memoryUsed])

  const latestMemoryLimit = latestNonNull(memoryLimit)
  // Memory byte columns only ship on historical ranges; the live broadcast
  // carries percent only. Without bytes, render the mem chart exactly as the
  // cpu/net charts do (percent axis, percent tooltip, caller-supplied summary).
  const hasMemoryData = latestNonNull(memoryUsed) != null || latestMemoryLimit != null
  const memorySummary = hasMemoryData
    ? (formatMemorySummary(mem, memoryUsed, memoryLimit) ?? memValue)
    : memValue
  const valueMap = { cpu: cpuValue, mem: memorySummary, net: netValue }

  const formatMemoryTooltip = useCallback((pct: number, index: number) => {
    const pctStr = `${pct.toFixed(1)}%`
    const usedValues = memoryUsedRef.current
    const limitValues = memoryLimitRef.current
    const used = index >= 0 ? usedValues?.[index] : undefined
    const limit = index >= 0 ? limitValues?.[index] : latestNonNull(limitValues)
    if (used != null && limit != null && limit > 0) {
      return [pctStr, `${formatBytes(used)} / ${formatBytes(limit)}`]
    }
    if (used != null) {
      return [pctStr, formatBytes(used)]
    }
    return pctStr
  }, [])

  const formatMemoryAxis = useCallback((pct: number) => {
    if (latestMemoryLimit == null || latestMemoryLimit <= 0) {
      return `${Math.round(pct)}%`
    }
    return formatBytes((latestMemoryLimit * pct) / 100)
  }, [latestMemoryLimit])

  return (
    <>
      {CHARTS.map(({ key, label, color, Icon }) => {
        const data = dataMap[key]
        const value = valueMap[key]
        return (
          <div key={key} className="bg-surface-2 rounded-lg p-3 border border-border overflow-hidden">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4" style={{ color: CHART_COLORS[color] }} />
                <span className="font-medium text-sm">{label}</span>
              </div>
              {value && <span className="text-xs text-muted-foreground">{value}</span>}
            </div>
            {data.length > 0 ? (
              <ResponsiveMiniChart
                data={data}
                timestamps={timestamps}
                color={color}
                height={CHART_HEIGHT}
                showAxes
                timeWindow={timeWindow}
                formatTooltipTime={formatTooltipTime}
                formatTooltipValue={key === 'mem' && hasMemoryData ? formatMemoryTooltip : undefined}
                formatYAxisTick={key === 'mem' && hasMemoryData ? formatMemoryAxis : undefined}
              />
            ) : (
              <div className="flex items-center justify-center text-muted-foreground text-xs" style={{ height: CHART_HEIGHT }}>
                No data available
              </div>
            )}
          </div>
        )
      })}
      {footer && (
        <p className="text-xs text-muted-foreground text-center">{footer}</p>
      )}
    </>
  )
}
