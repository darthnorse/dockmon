/**
 * useDashboardHosts - Fetch hosts with stats for dashboard view
 * Phase 4c
 *
 * FEATURES:
 * - Fetches hosts with current stats and sparkline data
 * - Supports grouping by tags (env, region, datacenter, etc.)
 * - Includes top containers per host
 * - Real-time updates via polling
 *
 * USAGE:
 * const { data, isLoading } = useDashboardHosts({ groupBy: 'env' })
 */

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'
import type { HostCardData } from '../components/HostCard'

export interface DashboardHostsParams {
  groupBy?: string // 'env', 'region', 'datacenter', 'compose.project', or custom label
  search?: string
  status?: 'online' | 'offline'
  alerts?: boolean
}

export interface DashboardHostsResponse {
  groups: Record<string, HostCardData[]>
  group_by: string | null
  total_hosts: number
}

/**
 * Fetch dashboard hosts with stats and grouping
 */
async function fetchDashboardHosts(params: DashboardHostsParams): Promise<DashboardHostsResponse> {
  const queryParams = new URLSearchParams()

  if (params.groupBy) queryParams.append('group_by', params.groupBy)
  if (params.search) queryParams.append('search', params.search)
  if (params.status) queryParams.append('status', params.status)
  if (params.alerts) queryParams.append('alerts', 'true')

  const url = `/dashboard/hosts${queryParams.toString() ? `?${queryParams.toString()}` : ''}`
  return await apiClient.get<DashboardHostsResponse>(url)
}

/**
 * Hook to fetch dashboard hosts with dynamic refresh based on DB polling_interval
 */
export function useDashboardHosts(params: DashboardHostsParams = {}, pollingInterval: number = 2) {
  // Convert polling_interval (in seconds) to milliseconds
  // Use the DB setting for real-time updates (default 2s)
  const refetchIntervalMs = pollingInterval * 1000

  return useQuery({
    queryKey: ['dashboard', 'hosts', params],
    queryFn: () => fetchDashboardHosts(params),
    staleTime: refetchIntervalMs / 2, // Half of polling interval
    refetchInterval: refetchIntervalMs, // Use DB polling_interval for live updates
  })
}
