/**
 * React Query hook for per-host metric capability.
 *
 * A host-scope metric rule targeting a host that reports no such metric can
 * never fire. Capability comes from samples actually arriving and still fresh,
 * so it reflects reality (e.g. a containerized agent missing /host/proc) rather
 * than connection type.
 */

import { useQuery } from '@tanstack/react-query'
import { apiClient } from '@/lib/api/client'

export interface HostMetricCapability {
  host_id: string
  host_name: string
  metrics: string[]
}

export interface MetricCapabilities {
  hosts: HostMetricCapability[]
  host_metrics: string[]
}

export function useMetricCapabilities(enabled = true) {
  return useQuery<MetricCapabilities>({
    queryKey: ['alert-metric-capabilities'],
    queryFn: async () => apiClient.get<MetricCapabilities>('/alerts/metrics/capabilities'),
    enabled,
    staleTime: 30_000,
  })
}

/**
 * Hosts among `hostIds` that are not currently reporting `metric`.
 * Returns [] while capabilities are unknown - never guess a warning.
 */
export function hostsMissingMetric(
  capabilities: MetricCapabilities | undefined,
  hostIds: string[],
  metric: string | undefined,
): HostMetricCapability[] {
  if (!capabilities || !metric || hostIds.length === 0) return []

  const targeted = new Set(hostIds)
  return capabilities.hosts.filter(
    (host) => targeted.has(host.host_id) && !host.metrics.includes(metric),
  )
}
