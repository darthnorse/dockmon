/**
 * HostEventsTab Component
 *
 * Events tab for host modal - Docker events
 */

import { HostEventsSection } from '../drawer/HostEventsSection'

interface HostEventsTabProps {
  hostId: string
}

export function HostEventsTab({ hostId }: HostEventsTabProps) {
  return (
    <div className="p-6">
      <HostEventsSection hostId={hostId} />
    </div>
  )
}
