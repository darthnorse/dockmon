/**
 * HostSettingsTab Component
 *
 * Settings tab for host modal - host configuration
 */

import { HostOverviewSection } from '../drawer/HostOverviewSection'
import { HostConnectionSection } from '../drawer/HostConnectionSection'

interface HostSettingsTabProps {
  hostId: string
  host: any
}

export function HostSettingsTab({ host }: HostSettingsTabProps) {
  return (
    <div className="p-6">
      <HostOverviewSection host={host} />
      <HostConnectionSection host={host} />
    </div>
  )
}
