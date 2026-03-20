import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import { VIEWS, detectGaps } from '@/lib/statsConfig'

export type TimeRange = 'live' | '1h' | '8h' | '24h' | '7d' | '30d'

interface StatsHistoryPoint {
  t: number
  cpu: number | null
  mem: number | null
  net: number | null
}

interface StatsHistoryResponse {
  range: string
  resolution: string
  interval: number
  points: number
  server_time: number
  data: StatsHistoryPoint[]
}

export function useStatsHistory(
  hostId: string | undefined,
  containerId: string | undefined,
  range: TimeRange,
) {
  const endpoint = containerId
    ? `/hosts/${hostId}/containers/${containerId}/stats/history`
    : `/hosts/${hostId}/stats/history`

  return useQuery<StatsHistoryResponse>({
    queryKey: ['stats-history', hostId, containerId ?? '__host__', range],
    queryFn: async () => {
      const resp = await apiClient.get<StatsHistoryResponse>(endpoint, { params: { range } })
      const view = VIEWS.find((v) => v.name === range)
      if (view && resp.data?.length > 1) {
        resp.data = detectGaps(resp.data, view.seconds) as StatsHistoryPoint[]
      }
      return resp
    },
    enabled: range !== 'live' && !!hostId,
    refetchInterval: range !== 'live' ? 10_000 : false,
    staleTime: 5_000,
  })
}
