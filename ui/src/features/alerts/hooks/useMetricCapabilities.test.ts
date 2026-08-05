import { describe, it, expect } from 'vitest'
import { hostsMissingMetric, type MetricCapabilities } from './useMetricCapabilities'

const AGENT_WITH_PROC = 'host-with-proc'
const AGENT_WITHOUT_PROC = 'host-without-proc'

const capabilities: MetricCapabilities = {
  hosts: [
    { host_id: AGENT_WITH_PROC, host_name: 'with-proc', metrics: ['cpu_percent', 'memory_percent'] },
    { host_id: AGENT_WITHOUT_PROC, host_name: 'without-proc', metrics: [] },
  ],
  host_metrics: ['cpu_percent', 'memory_percent'],
}

describe('hostsMissingMetric', () => {
  it('flags a targeted host that reports nothing', () => {
    const missing = hostsMissingMetric(
      capabilities,
      [AGENT_WITH_PROC, AGENT_WITHOUT_PROC],
      'cpu_percent',
    )
    expect(missing.map((h) => h.host_name)).toEqual(['without-proc'])
  })

  it('ignores hosts the rule does not target', () => {
    expect(hostsMissingMetric(capabilities, [AGENT_WITH_PROC], 'memory_percent')).toEqual([])
  })

  // disk_percent has no producer today, so every host is correctly flagged.
  it('flags every host for a metric nothing reports', () => {
    const missing = hostsMissingMetric(
      capabilities,
      [AGENT_WITH_PROC, AGENT_WITHOUT_PROC],
      'disk_percent',
    )
    expect(missing).toHaveLength(2)
  })

  // Never warn on unknown data - an unloaded query must not imply a broken rule.
  it('returns nothing while capabilities are unknown', () => {
    expect(hostsMissingMetric(undefined, [AGENT_WITHOUT_PROC], 'cpu_percent')).toEqual([])
  })

  it('returns nothing without a metric or targets', () => {
    expect(hostsMissingMetric(capabilities, [AGENT_WITHOUT_PROC], undefined)).toEqual([])
    expect(hostsMissingMetric(capabilities, [], 'cpu_percent')).toEqual([])
  })
})
