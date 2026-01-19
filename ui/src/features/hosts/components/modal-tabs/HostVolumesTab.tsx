/**
 * HostVolumesTab Component
 *
 * Volumes tab for host modal - shows Docker volumes with usage information
 */

import { useState, useMemo } from 'react'
import { Search, Filter, HardDrive } from 'lucide-react'
import { useHostVolumes } from '../../hooks/useHostVolumes'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ContainerLinkList } from '@/components/shared/ContainerLinkList'
import { formatRelativeTime } from '@/lib/utils/eventUtils'
import type { DockerVolume } from '@/types/api'

interface HostVolumesTabProps {
  hostId: string
}

function VolumeStatusBadge({ volume }: { volume: DockerVolume }) {
  if (volume.in_use) {
    return (
      <StatusBadge variant="success">
        In Use ({volume.container_count})
      </StatusBadge>
    )
  }
  return (
    <StatusBadge variant="muted">
      Unused
    </StatusBadge>
  )
}

export function HostVolumesTab({ hostId }: HostVolumesTabProps) {
  const { data: volumes, isLoading, error } = useHostVolumes(hostId)

  // UI state
  const [searchQuery, setSearchQuery] = useState('')
  const [showUnusedOnly, setShowUnusedOnly] = useState(false)

  // Filter volumes
  const filteredVolumes = useMemo(() => {
    if (!volumes) return []

    return volumes.filter((volume) => {
      // Apply unused filter
      if (showUnusedOnly && volume.in_use) return false

      // Apply search filter (search in name and driver)
      if (searchQuery) {
        const query = searchQuery.toLowerCase()
        return (
          volume.name.toLowerCase().includes(query) ||
          volume.driver.toLowerCase().includes(query)
        )
      }

      return true
    })
  }, [volumes, showUnusedOnly, searchQuery])

  // Count of unused volumes
  const unusedCount = useMemo(() => {
    return volumes?.filter((vol) => !vol.in_use).length ?? 0
  }, [volumes])

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 rounded-full border-accent border-t-transparent" />
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="p-6">
        <div className="bg-danger/10 text-danger p-4 rounded-lg">
          Failed to load volumes: {error.message}
        </div>
      </div>
    )
  }

  // Empty state
  if (!volumes || volumes.length === 0) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <HardDrive className="h-12 w-12 mx-auto mb-3 opacity-50" />
        No volumes found on this host.
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header with search and actions */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search volumes..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-surface-2 border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-accent"
          />
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {/* Show unused toggle */}
          <button
            onClick={() => setShowUnusedOnly(!showUnusedOnly)}
            className={`flex items-center gap-2 px-3 py-2 text-sm rounded-lg border transition-colors ${
              showUnusedOnly
                ? 'bg-accent text-accent-foreground border-accent'
                : 'bg-surface-2 text-foreground border-border hover:bg-surface-3'
            }`}
          >
            <Filter className="h-4 w-4" />
            Unused Only
            {unusedCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 bg-black/20 rounded text-xs">
                {unusedCount}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Volume count */}
      <div className="text-sm text-muted-foreground">
        Showing {filteredVolumes.length} of {volumes.length} volumes
      </div>

      {/* Volumes table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-surface-2 border-b border-border">
            <tr>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Name</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden md:table-cell">Driver</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden 2xl:table-cell">Created</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Status</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden xl:table-cell">Containers</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filteredVolumes.map((volume) => (
              <tr
                key={volume.name}
                className="hover:bg-surface-2 transition-colors"
              >
                <td className="p-3">
                  <div className="text-sm font-medium font-mono truncate max-w-[300px]" title={volume.name}>
                    {volume.name}
                  </div>
                </td>
                <td className="p-3 hidden md:table-cell">
                  <span className="inline-flex items-center px-2 py-1 text-xs rounded-full bg-muted/30 text-muted-foreground">
                    {volume.driver}
                  </span>
                </td>
                <td className="p-3 hidden 2xl:table-cell">
                  <span className="text-sm text-muted-foreground">
                    {formatRelativeTime(volume.created)}
                  </span>
                </td>
                <td className="p-3">
                  <VolumeStatusBadge volume={volume} />
                </td>
                <td className="p-3 hidden xl:table-cell">
                  <ContainerLinkList containers={volume.containers} hostId={hostId} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Empty filtered state */}
      {filteredVolumes.length === 0 && volumes.length > 0 && (
        <div className="text-center text-muted-foreground py-8">
          No volumes match your filters.
        </div>
      )}
    </div>
  )
}
