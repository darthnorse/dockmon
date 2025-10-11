/**
 * HostLiveStatsTab Component
 *
 * Live Stats tab for host modal - real-time metrics
 */

import { HostPerformanceSection } from '../drawer/HostPerformanceSection'

interface HostLiveStatsTabProps {
  hostId: string
}

export function HostLiveStatsTab({ hostId }: HostLiveStatsTabProps) {
  return (
    <div className="p-6">
      <HostPerformanceSection hostId={hostId} />
    </div>
  )
}
