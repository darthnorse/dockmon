import { describe, it, expect } from 'vitest'
import {
  agentMountRemedy,
  anyAgentHost,
  hostsMissingMetric,
  isHostMetricRule,
  hostsNeedingMetricWarning,
  isCollectedHostMetric,
  type MetricCapabilities,
} from './useMetricCapabilities'

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

describe('isCollectedHostMetric', () => {
  // disk_percent has no producer at any layer, so the rule can never fire and
  // the /host/proc remedy would send the user down a dead end.
  it('is false for a metric nothing collects', () => {
    expect(isCollectedHostMetric(capabilities, 'disk_percent')).toBe(false)
  })

  it('is true for a collected metric', () => {
    expect(isCollectedHostMetric(capabilities, 'cpu_percent')).toBe(true)
  })

  it('assumes collected while capabilities are unknown', () => {
    expect(isCollectedHostMetric(undefined, 'disk_percent')).toBe(true)
  })
})

describe('hostsNeedingMetricWarning', () => {
  const agentOffline = { id: AGENT_WITHOUT_PROC, status: 'offline', connection_type: 'agent' }
  const agentOnline = { id: AGENT_WITHOUT_PROC, status: 'online', connection_type: 'agent' }
  const dockerOnline = { id: AGENT_WITH_PROC, status: 'online', connection_type: 'remote' }

  // An offline host has an obvious reason to report nothing; the backend
  // suppresses its equivalent warning too.
  it('skips offline hosts', () => {
    expect(hostsNeedingMetricWarning(capabilities, [agentOffline], 'cpu_percent')).toEqual([])
  })

  it('flags an online host that reports nothing', () => {
    const flagged = hostsNeedingMetricWarning(capabilities, [agentOnline, dockerOnline], 'cpu_percent')
    expect(flagged.map((h) => h.host_name)).toEqual(['without-proc'])
  })

  // An uncollectable metric is reported by its own message, not per host.
  it('returns nothing for a metric nothing collects', () => {
    expect(hostsNeedingMetricWarning(capabilities, [agentOnline], 'disk_percent')).toEqual([])
  })
})

describe('anyAgentHost', () => {
  it('is true when a flagged host is an agent', () => {
    const flagged = [{ host_id: AGENT_WITHOUT_PROC, host_name: 'without-proc', metrics: [] }]
    expect(anyAgentHost(flagged, [{ id: AGENT_WITHOUT_PROC, connection_type: 'agent' }])).toBe(true)
  })

  // The /host/proc remedy is meaningless for an mTLS or local Docker host.
  it('is false when every flagged host is a Docker host', () => {
    const flagged = [{ host_id: AGENT_WITH_PROC, host_name: 'with-proc', metrics: [] }]
    expect(anyAgentHost(flagged, [{ id: AGENT_WITH_PROC, connection_type: 'remote' }])).toBe(false)
  })
})

// The rule form keeps formData.metric when the user switches to an event-driven
// rule kind, and the submit path drops it. The capability warning must drop it
// too, or a "Host Offline" rule carrying a leftover disk_percent is told it will
// never fire.
describe('isHostMetricRule', () => {
  it('is not treated as a metric rule when the kind needs no metric', () => {
    expect(isHostMetricRule('host', false, 'disk_percent')).toBe(false)
  })

  it('is still a metric rule when the kind needs one', () => {
    expect(isHostMetricRule('host', true, 'cpu_percent')).toBe(true)
  })

  it('is not a metric rule for container scope', () => {
    expect(isHostMetricRule('container', true, 'cpu_percent')).toBe(false)
  })

  it('is not a metric rule with no metric selected', () => {
    expect(isHostMetricRule('host', true, undefined)).toBe(false)
  })
})

describe('agentMountRemedy', () => {
  it('names /host/proc for CPU and memory', () => {
    expect(agentMountRemedy('cpu_percent')).toBe('-v /proc:/host/proc:ro')
    expect(agentMountRemedy('memory_percent')).toBe('-v /proc:/host/proc:ro')
  })

  // Disk rides on the host sample, so a containerized agent needs both mounts.
  it('names /hostfs alongside /host/proc for disk', () => {
    expect(agentMountRemedy('disk_percent')).toBe('-v /proc:/host/proc:ro -v /:/hostfs:ro')
  })
})

describe('disk_percent capability', () => {
  const withDisk: MetricCapabilities = {
    hosts: [
      { host_id: AGENT_WITH_PROC, host_name: 'with-hostfs', metrics: ['cpu_percent', 'memory_percent', 'disk_percent'] },
      { host_id: AGENT_WITHOUT_PROC, host_name: 'no-hostfs', metrics: ['cpu_percent', 'memory_percent'] },
    ],
    host_metrics: ['cpu_percent', 'disk_percent', 'memory_percent'],
  }

  it('is collected once the backend advertises it', () => {
    expect(isCollectedHostMetric(withDisk, 'disk_percent')).toBe(true)
  })

  it('flags only the host not reporting disk', () => {
    const flagged = hostsNeedingMetricWarning(
      withDisk,
      [
        { id: AGENT_WITH_PROC, status: 'online', connection_type: 'agent' },
        { id: AGENT_WITHOUT_PROC, status: 'online', connection_type: 'agent' },
      ],
      'disk_percent',
    )
    expect(flagged.map((h) => h.host_name)).toEqual(['no-hostfs'])
  })
})
