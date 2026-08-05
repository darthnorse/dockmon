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

/** A host as the rule form knows it - only the fields the warning depends on. */
export interface TargetedHost {
  id: string
  status?: string
  connection_type?: string | undefined
}

/**
 * Whether DockMon collects `metric` for hosts at all. A metric no producer
 * serves (a rule kind whose metric was never wired up) is a different problem
 * from a host that is not currently reporting one that is.
 * Unknown capabilities count as collected - never guess a warning.
 */
export function isCollectedHostMetric(
  capabilities: MetricCapabilities | undefined,
  metric: string | undefined,
): boolean {
  if (!capabilities || !metric) return true
  return capabilities.host_metrics.includes(metric)
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

/**
 * Targeted hosts worth warning about: online (an offline host has an obvious
 * reason to report nothing) and not reporting the metric. Mirrors the backend's
 * own warning gate in _report_host_without_metrics.
 */
export function hostsNeedingMetricWarning(
  capabilities: MetricCapabilities | undefined,
  targeted: TargetedHost[],
  metric: string | undefined,
): HostMetricCapability[] {
  if (!isCollectedHostMetric(capabilities, metric)) return []

  const online = targeted.filter((host) => host.status === 'online')
  return hostsMissingMetric(capabilities, online.map((h) => h.id), metric)
}

/** Whether any flagged host is an agent, so the /host/proc remedy applies. */
export function anyAgentHost(
  flagged: HostMetricCapability[],
  targeted: TargetedHost[],
): boolean {
  const byId = new Map(targeted.map((h) => [h.id, h]))
  return flagged.some((host) => byId.get(host.host_id)?.connection_type === 'agent')
}
