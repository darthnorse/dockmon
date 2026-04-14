import { StatsCharts } from '@/lib/charts/StatsCharts'
import { LIVE_TIME_WINDOW } from '@/lib/statsConfig'
import { StatsTimeRangeSelector } from './StatsTimeRangeSelector'
import { useLastSelectedRange } from './useLastSelectedRange'
import { useStatsHistory } from './useStatsHistory'
import type { HistoricalRange, StatsHistoryResponse } from './historyTypes'

interface LiveData {
  cpu: (number | null)[]
  mem: (number | null)[]
  net: (number | null)[]
  timestamps: number[]
  cpuValue?: string | undefined
  memValue?: string | undefined
  netValue?: string | undefined
}

interface Props {
  hostId: string
  containerId?: string
  liveData: LiveData
}

/**
 * Composition of the time-range selector, the existing StatsCharts, and
 * historical loading/error states. Keep this component boundary narrow:
 * it knows only about hostId + optional containerId + generic live data
 * arrays; it does not care whether the caller is a container or a host
 * view.
 */
export function StatsSection({ hostId, containerId, liveData }: Props) {
  const [range, setRange] = useLastSelectedRange()

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Stats</h3>
        <StatsTimeRangeSelector value={range} onChange={setRange} />
      </div>
      {range === 'live' ? (
        <StatsCharts
          cpu={liveData.cpu}
          mem={liveData.mem}
          net={liveData.net}
          timestamps={liveData.timestamps}
          timeWindow={LIVE_TIME_WINDOW}
          cpuValue={liveData.cpuValue}
          memValue={liveData.memValue}
          netValue={liveData.netValue}
        />
      ) : (
        <HistoricalCharts
          hostId={hostId}
          {...(containerId !== undefined && { containerId })}
          range={range}
        />
      )}
    </div>
  )
}

function HistoricalCharts({
  hostId, containerId, range,
}: {
  hostId: string
  containerId?: string
  range: HistoricalRange
}) {
  const { data, isLoading, error, refetch } = useStatsHistory(hostId, containerId, range)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8 text-muted-foreground text-sm">
        Loading history...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-3">
        <p className="text-sm text-muted-foreground">
          Failed to load history.
        </p>
        <button
          type="button"
          onClick={() => refetch()}
          className="px-3 py-1 text-xs rounded bg-primary text-primary-foreground hover:opacity-90"
        >
          Retry
        </button>
      </div>
    )
  }

  if (!data) return null

  const nonNullCpu = data.cpu.filter((v) => v !== null).length
  const footer = `${nonNullCpu} data points (${data.interval_seconds}s resolution)`

  return (
    <StatsCharts
      cpu={data.cpu}
      mem={data.mem}
      net={data.net_bps}
      timestamps={data.timestamps}
      timeWindow={data.tier_seconds}
      cpuValue={formatLatestValue(data.cpu, '%')}
      memValue={formatMemValue(data)}
      netValue={formatLatestValue(data.net_bps, ' B/s')}
      footer={footer}
    />
  )
}

function formatLatestValue(arr: (number | null)[], suffix: string): string | undefined {
  for (let i = arr.length - 1; i >= 0; i--) {
    const v = arr[i]
    if (v !== null && v !== undefined) {
      return `${Math.round(v * 10) / 10}${suffix}`
    }
  }
  return undefined
}

function formatMemValue(data: StatsHistoryResponse): string | undefined {
  const latestPct = formatLatestValue(data.mem, '%')
  const used = latestNonNull(data.memory_used_bytes)
  const limit = latestNonNull(data.memory_limit_bytes)
  if (latestPct === undefined) return undefined
  if (used !== undefined && limit !== undefined && limit > 0) {
    return `${latestPct} (${formatBytes(used)} / ${formatBytes(limit)})`
  }
  return latestPct
}

function latestNonNull(arr: (number | null)[] | undefined): number | undefined {
  if (!arr) return undefined
  for (let i = arr.length - 1; i >= 0; i--) {
    const v = arr[i]
    if (v !== null && v !== undefined) return v
  }
  return undefined
}

function formatBytes(n: number): string {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(1)} ${units[i]}`
}
