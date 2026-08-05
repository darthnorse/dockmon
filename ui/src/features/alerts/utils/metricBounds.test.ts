import { describe, it, expect } from 'vitest'
import { MAX_CPU_THRESHOLD, maxThresholdFor } from './metricBounds'

// The form's threshold bound must match what the API accepts, or the API
// rejects values the form happily submits. Container CPU can exceed 100% on
// multi-core hosts; host CPU is a single normalised percentage (issue #243).
describe('maxThresholdFor', () => {
  it('allows multi-core headroom for container CPU', () => {
    expect(maxThresholdFor('container', 'cpu_percent')).toBe(MAX_CPU_THRESHOLD)
  })

  it('caps host CPU at 100', () => {
    expect(maxThresholdFor('host', 'cpu_percent')).toBe(100)
  })

  it('caps percentage metrics at 100 in either scope', () => {
    expect(maxThresholdFor('container', 'memory_percent')).toBe(100)
    expect(maxThresholdFor('host', 'memory_percent')).toBe(100)
    expect(maxThresholdFor('host', 'disk_percent')).toBe(100)
  })

  it('falls back to 100 when no metric is selected yet', () => {
    expect(maxThresholdFor('host', undefined)).toBe(100)
  })

  it('leaves byte-valued metrics unbounded', () => {
    // No rule kind offers these, but an API-created rule loads into this form,
    // where a 100 cap would be nonsense for a byte threshold.
    expect(maxThresholdFor('container', 'memory_usage')).toBeUndefined()
    expect(maxThresholdFor('container', 'memory_limit')).toBeUndefined()
  })
})
