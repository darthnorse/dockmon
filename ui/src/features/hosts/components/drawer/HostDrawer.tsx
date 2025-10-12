/**
 * HostDrawer Component
 *
 * Main drawer component for displaying host details
 * Combines all sections: Overview, Connection, Performance, Containers, Events
 */

import { Edit, Trash2, Maximize2 } from 'lucide-react'
import { Drawer } from '@/components/ui/drawer'
import { HostOverviewSection } from './HostOverviewSection'
import { HostTagsSection } from './HostTagsSection'
import { HostConnectionSection } from './HostConnectionSection'
import { HostPerformanceSection } from './HostPerformanceSection'
import { HostContainersSection } from './HostContainersSection'
import { HostEventsSection } from './HostEventsSection'

export interface HostDrawerProps {
  /**
   * Host ID to display
   */
  hostId: string | null

  /**
   * Host data (from useHosts query)
   */
  host: any

  /**
   * Whether drawer is open
   */
  open: boolean

  /**
   * Callback when drawer closes
   */
  onClose: () => void

  /**
   * Callback when Edit button is clicked
   */
  onEdit?: (hostId: string) => void

  /**
   * Callback when Delete button is clicked
   */
  onDelete?: (hostId: string) => void

  /**
   * Callback when Expand button is clicked (opens full modal)
   */
  onExpand?: (hostId: string) => void
}

export function HostDrawer({
  hostId,
  host,
  open,
  onClose,
  onEdit,
  onDelete,
  onExpand,
}: HostDrawerProps) {
  if (!hostId || !host) return null

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={host.name}
      width="w-[600px]"
    >
      {/* Action Buttons */}
      <div className="px-6 py-4 border-b border-border bg-muted/30">
        <div className="flex items-center gap-2">
          {onEdit && (
            <button
              onClick={() => onEdit(hostId)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-background hover:bg-muted border border-border transition-colors text-sm"
            >
              <Edit className="h-4 w-4" />
              <span>Edit Host</span>
            </button>
          )}

          {onExpand && (
            <button
              onClick={() => onExpand(hostId)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent hover:bg-accent/90 text-accent-foreground transition-colors text-sm"
            >
              <Maximize2 className="h-4 w-4" />
              <span>Expand</span>
            </button>
          )}

          <div className="flex-1" />

          {onDelete && (
            <button
              onClick={() => onDelete(hostId)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-500 border border-red-500/20 transition-colors text-sm"
            >
              <Trash2 className="h-4 w-4" />
              <span>Delete</span>
            </button>
          )}
        </div>
      </div>

      {/* Sections */}
      <HostOverviewSection host={host} />
      <HostTagsSection host={host} />
      <HostConnectionSection host={host} />
      <HostPerformanceSection hostId={hostId} />
      <HostContainersSection hostId={hostId} />
      <HostEventsSection hostId={hostId} />
    </Drawer>
  )
}
