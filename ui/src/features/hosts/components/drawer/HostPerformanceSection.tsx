/**
 * HostPerformanceSection Component
 *
 * Displays Live + historical CPU/Memory/Network charts for a host via
 * the shared StatsSection composition (selector + charts).
 */

import { DrawerSection } from '@/components/ui/drawer'
import { StatsSection } from '@/lib/stats/StatsSection'
import { useHostMetrics, useHostSparklines } from '@/lib/stats/StatsProvider'
import { formatNetworkRate } from '@/lib/utils/formatting'

interface HostPerformanceSectionProps {
  hostId: string
}

export function HostPerformanceSection({ hostId }: HostPerformanceSectionProps) {
  const metrics = useHostMetrics(hostId)
  const sparklines = useHostSparklines(hostId)

  return (
    <DrawerSection title="Performance">
      <StatsSection
        hostId={hostId}
        liveData={{
          cpu: sparklines?.cpu ?? [],
          mem: sparklines?.mem ?? [],
          net: sparklines?.net ?? [],
          timestamps: [],
          cpuValue:
            metrics?.cpu_percent !== undefined
              ? `${metrics.cpu_percent.toFixed(1)}%`
              : undefined,
          memValue:
            metrics?.mem_percent !== undefined
              ? `${metrics.mem_percent.toFixed(1)}%`
              : undefined,
          netValue:
            metrics?.net_bytes_per_sec !== undefined
              ? formatNetworkRate(metrics.net_bytes_per_sec)
              : undefined,
        }}
      />
    </DrawerSection>
  )
}
