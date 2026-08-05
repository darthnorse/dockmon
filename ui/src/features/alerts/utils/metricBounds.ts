// CPU is the one metric that legitimately exceeds 100%: a container can use
// several cores. A host reports a single normalised percentage, so the same
// allowance there would only ever produce a rule that cannot fire.
export const MAX_CPU_THRESHOLD = 6400

const CPU_METRIC = 'cpu_percent'

export function maxThresholdFor(scope: string, metric: string | undefined): number {
  return metric === CPU_METRIC && scope === 'container' ? MAX_CPU_THRESHOLD : 100
}
