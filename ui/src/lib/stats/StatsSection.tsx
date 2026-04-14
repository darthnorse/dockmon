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
 * Selector + StatsCharts + historical loading/error states. Entity-agnostic:
 * takes hostId, optional containerId, and generic live arrays.
 */
export function StatsSection({ hostId, containerId, liveData }: Props) {
  const [range, setRange] = useLastSelectedRange()

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
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

  // Keep the spinner while any fetch has no data yet — prevents the chart
  // area from briefly returning null during a range-change transition.
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
  return v === undefined ? undefined : formatNetworkRate(v)
}

function formatMemValue(data: StatsHistoryResponse): string | undefined {
  const latestPct = formatPercent(data.mem)
  if (latestPct === undefined) return undefined
  const used = latestNonNull(data.memory_used_bytes)
  const limit = latestNonNull(data.memory_limit_bytes)
  if (used === undefined) return latestPct
  // Show absolute used bytes even when limit is 0/undefined (unlimited cgroup).
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
