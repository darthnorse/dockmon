/**
 * Containers tab for the host modal.
 *
 * Owns its own scroll container because the modal's `body { overflow:
 * hidden }` makes window-scroll virtualization unreachable for hosts
 * with hundreds of containers.
 */

import { useState } from 'react'

import { ContainerTable } from '@/features/containers/ContainerTable'

interface HostContainersTabProps {
  hostId: string
}

export function HostContainersTab({ hostId }: HostContainersTabProps) {
  // Callback ref via setState so the second render hands the attached
  // element to ContainerTable. `h-full` keeps the outer Tabs scroll
  // inactive so this div is the only scroller.
  const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null)
  return (
    <div ref={setScrollEl} data-testid="host-containers-scroll" className="h-full overflow-y-auto p-6">
      <ContainerTable hostId={hostId} scrollElement={scrollEl} />
    </div>
  )
}
