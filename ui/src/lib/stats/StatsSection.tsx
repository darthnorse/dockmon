import { StatsCharts } from '@/lib/charts/StatsCharts'
import { formatNetworkRate } from '@/lib/utils/formatting'
import { StatsTimeRangeSelector } from './StatsTimeRangeSelector'
import { useLastSelectedRange } from './useLastSelectedRange'
import { useStatsHistory } from './useStatsHistory'
import { useLiveHistory } from './useLiveHistory'
import { latestNonNull, formatMemorySummary } from './columnUtils'
import type { HistoricalRange } from './historyTypes'

interface LiveData {
  cpu: (number | null)[]
  mem: (number | null)[]
  net: (number | null)[]
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
        <LiveCharts hostId={hostId} containerId={containerId} liveData={liveData} />
      ) : (
        <HistoricalCharts hostId={hostId} containerId={containerId} range={range} />
      )}
    </div>
  )
}

/**
 * Detail-view Live chart. Fetches the configured window once from the live
 * endpoint (extended series: absolute time + memory bytes) and keeps it current
 * by appending the newest broadcast tick. Falls back to the lean broadcast
 * sparkline (index mode, no memory labels) while the one-time fetch is in
 * flight, so the chart is never blank on open.
 */
function LiveCharts({
  hostId, containerId, liveData,
}: {
  hostId: string
  containerId: string | undefined
  liveData: LiveData
}) {
  const live = useLiveHistory(hostId, containerId)
  const windowSeconds = live.windowSeconds

  if (live.data && live.data.timestamps.length > 0) {
    const d = live.data
    return (
      <StatsCharts
        cpu={d.cpu}
        mem={d.mem}
        net={d.net}
        memoryUsed={d.memory_used_bytes}
        memoryLimit={d.memory_limit_bytes}
        timestamps={d.timestamps}
        timeWindow={windowSeconds}
        cpuValue={liveData.cpuValue}
        memValue={liveData.memValue}
        netValue={liveData.netValue}
      />
    )
  }

  return (
    <StatsCharts
      cpu={liveData.cpu}
      mem={liveData.mem}
      net={liveData.net}
      timestamps={[]}
      timeWindow={windowSeconds}
      cpuValue={liveData.cpuValue}
      memValue={liveData.memValue}
      netValue={liveData.netValue}
    />
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
          disabled={isFetching}
          aria-busy={isFetching}
          className="px-3 py-1 text-xs rounded bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isFetching ? 'Retrying…' : 'Retry'}
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
      memoryUsed={data.memory_used_bytes}
      memoryLimit={data.memory_limit_bytes}
      timestamps={data.timestamps}
      timeWindow={data.tier_seconds}
      cpuValue={formatPercent(data.cpu)}
      memValue={formatMemorySummary(data.mem, data.memory_used_bytes, data.memory_limit_bytes)}
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
