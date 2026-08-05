// CPU is the one metric that legitimately exceeds 100%: a container can use
// several cores. A host reports a single normalised percentage, so the same
// allowance there would only ever produce a rule that cannot fire.
export const MAX_CPU_THRESHOLD = 6400

const CPU_METRIC = 'cpu_percent'

// Byte-valued metrics have no upper bound. No rule kind offers them, but an
// API-created rule still loads into this form, where a 100 cap would be absurd.
const BYTE_METRICS = new Set(['memory_usage', 'memory_limit'])

export function maxThresholdFor(scope: string, metric: string | undefined): number | undefined {
  if (metric && BYTE_METRICS.has(metric)) return undefined
  return metric === CPU_METRIC && scope === 'container' ? MAX_CPU_THRESHOLD : 100
}
