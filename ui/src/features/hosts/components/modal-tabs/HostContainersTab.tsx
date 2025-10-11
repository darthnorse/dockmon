/**
 * HostContainersTab Component
 *
 * Containers tab for host modal - shows full container table
 */

import { ContainerTable } from '@/features/containers/ContainerTable'

interface HostContainersTabProps {
  hostId: string
}

export function HostContainersTab({ hostId }: HostContainersTabProps) {
  return (
    <div className="p-6">
      <ContainerTable hostId={hostId} />
    </div>
  )
}
