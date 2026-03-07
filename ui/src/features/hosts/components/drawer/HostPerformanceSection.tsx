/**
 * HostPerformanceSection Component
 *
 * Displays real-time CPU/Memory/Network sparklines for a host
 */

import { useState, useMemo } from 'react'
import { DrawerSection } from '@/components/ui/drawer'
import { useHostMetrics, useHostSparklines } from '@/lib/stats/StatsProvider'
import { StatsCharts } from '@/lib/charts/StatsCharts'
import { StatsTimeRangeSelector } from '@/features/containers/components/StatsTimeRangeSelector'
import { useStatsHistory, type TimeRange } from '@/features/containers/hooks/useStatsHistory'
import { VIEWS, LIVE_TIME_WINDOW, DEFAULT_HIST_TIME_WINDOW } from '@/lib/statsConfig'

interface HostPerformanceSectionProps {
  hostId: string
}

export function HostPerformanceSection({ hostId }: HostPerformanceSectionProps) {
  const metrics = useHostMetrics(hostId)
  const sparklines = useHostSparklines(hostId)
  const [timeRange, setTimeRange] = useState<TimeRange>('live')
  const { data: historyData } = useStatsHistory(hostId, undefined, timeRange)
  const hist = useMemo(() => {
    const d = historyData?.data ?? []
    return {
      cpu: d.map((p) => p.cpu),
      mem: d.map((p) => p.mem),
      net: d.map((p) => p.net_rx),
      timestamps: d.map((p) => p.t / 1000),
    }
  }, [historyData])
  const histTimeWindow = VIEWS.find(v => v.name === timeRange)?.seconds

  const formatNetworkRate = (bytesPerSec: number | undefined): string => {
    if (!bytesPerSec) return '0 B/s'
    if (bytesPerSec < 1024) return `${bytesPerSec.toFixed(0)} B/s`
    if (bytesPerSec < 1024 * 1024) return `${(bytesPerSec / 1024).toFixed(1)} KB/s`
    return `${(bytesPerSec / (1024 * 1024)).toFixed(1)} MB/s`
  }

  const formatBytes = (bytes: number | undefined): string => {
    if (!bytes) return '0 B'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let value = bytes
    let unitIndex = 0
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024
      unitIndex++
    }
    return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unitIndex]}`
  }


  return (
    <DrawerSection title="Performance">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-muted-foreground">
            {timeRange === 'live' ? 'Live Stats' : 'Historical Stats'}
          </span>
          <StatsTimeRangeSelector value={timeRange} onChange={setTimeRange} />
        </div>

        {timeRange === 'live' ? (
          <StatsCharts
            cpu={sparklines?.cpu ?? []}
            mem={sparklines?.mem ?? []}
            net={sparklines?.net ?? []}
            timestamps={sparklines?.timestamps ?? []}
            timeWindow={LIVE_TIME_WINDOW}
            cpuValue={metrics?.cpu_percent !== undefined ? `${metrics.cpu_percent.toFixed(1)}%` : undefined}
            memValue={metrics?.mem_bytes ? formatBytes(metrics.mem_bytes) : undefined}
            netValue={metrics?.net_bytes_per_sec !== undefined ? formatNetworkRate(metrics.net_bytes_per_sec) : undefined}
          />
        ) : (
          <StatsCharts
            cpu={hist.cpu}
            mem={hist.mem}
            net={hist.net}
            timestamps={hist.timestamps}
            timeWindow={histTimeWindow ?? DEFAULT_HIST_TIME_WINDOW}
            footer={historyData ? `${historyData.points} data points (${historyData.resolution} resolution)` : undefined}
          />
        )}
      </div>
    </DrawerSection>
  )
}
