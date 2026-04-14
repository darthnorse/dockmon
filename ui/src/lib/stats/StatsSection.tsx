import { StatsCharts } from '@/lib/charts/StatsCharts'
import { LIVE_TIME_WINDOW } from '@/lib/statsConfig'
import { formatBytes, formatNetworkRate } from '@/lib/utils/formatting'
import { StatsTimeRangeSelector } from './StatsTimeRangeSelector'
import { useLastSelectedRange } from './useLastSelectedRange'
import { useStatsHistory } from './useStatsHistory'
import type { HistoricalRange, StatsHistoryResponse } from './historyTypes'

interface Props {
  hostId: string
  containerId?: string
  liveData: {
    cpu: (number | null)[]
    mem: (number | null)[]
    net: (number | null)[]
    cpuValue?: string | undefined
    memValue?: string | undefined
    netValue?: string | undefined
  }
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
          timestamps={[]}
          timeWindow={LIVE_TIME_WINDOW}
          cpuValue={liveData.cpuValue}
          memValue={liveData.memValue}
          netValue={liveData.netValue}
        />
      ) : (
        <HistoricalCharts hostId={hostId} containerId={containerId} range={range} />
      )}
    </div>
  )
}

function HistoricalCharts({
  hostId, containerId, range,
}: {
  hostId: string
  containerId: string | undefined
  range: HistoricalRange
}) {
  const { data, isLoading, isFetching, error, refetch } = useStatsHistory(hostId, containerId, range)

  // Show the loading spinner for any fetch that has no data yet — covers both
  // the first mount (isLoading) and the brief transition after a range change
  // where isLoading has flipped to false but the new data hasn't hydrated yet.
  // Without this, the chart area briefly returns null and the layout shifts.
  if (!data && (isLoading || isFetching)) {
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
      cpuValue={formatPercent(data.cpu)}
      memValue={formatMemValue(data)}
      netValue={formatNetValue(data.net_bps)}
      footer={footer}
    />
  )
}

function formatPercent(arr: (number | null)[]): string | undefined {
  const v = latestNonNull(arr)
  return v === undefined ? undefined : `${Math.round(v * 10) / 10}%`
}

function formatNetValue(arr: (number | null)[]): string | undefined {
  const v = latestNonNull(arr)
  // Route through the project-wide formatter so historical and live panels
  // render the same byte reading with identical units (KB/s/MB/s/etc.).
  return v === undefined ? undefined : formatNetworkRate(v)
}

function formatMemValue(data: StatsHistoryResponse): string | undefined {
  const latestPct = formatPercent(data.mem)
  if (latestPct === undefined) return undefined
  const used = latestNonNull(data.memory_used_bytes)
  const limit = latestNonNull(data.memory_limit_bytes)
  // Prefer the full "X% (used / limit)" form when limit is known (cgroups
  // reports a finite cap). When limit is 0/undefined (unlimited container),
  // still show absolute used bytes if available — matches the live view.
  if (used === undefined) return latestPct
  if (limit !== undefined && limit > 0) {
    return `${latestPct} (${formatBytes(used)} / ${formatBytes(limit)})`
  }
  return `${latestPct} (${formatBytes(used)})`
}

function latestNonNull(arr: (number | null)[] | undefined): number | undefined {
  if (!arr) return undefined
  for (let i = arr.length - 1; i >= 0; i--) {
    const v = arr[i]
    if (v !== null && v !== undefined) return v
  }
  return undefined
}
