/**
 * HostDrawer Component
 *
 * Main drawer component for displaying host details
 * Combines all sections: Overview, Connection, Performance, Containers, Events
 */

import { useState } from 'react'
import { Edit, Trash2, Maximize2, AlertTriangle } from 'lucide-react'
import { Drawer } from '@/components/ui/drawer'
import { HostOverviewSection } from './HostOverviewSection'
import { HostTagsSection } from './HostTagsSection'
import { HostConnectionSection } from './HostConnectionSection'
import { HostPerformanceSection } from './HostPerformanceSection'
import { HostContainersSection } from './HostContainersSection'
import { HostEventsSection } from './HostEventsSection'
import { useDeleteHost } from '../../hooks/useHosts'

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
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const deleteMutation = useDeleteHost()

  if (!hostId || !host) return null

  const handleDeleteClick = () => {
    setShowDeleteConfirm(true)
  }

  const handleDeleteConfirm = async () => {
    try {
      await deleteMutation.mutateAsync(hostId)
      setShowDeleteConfirm(false)
      onClose()
      if (onDelete) {
        onDelete(hostId)
      }
    } catch (error) {
      // Error is handled by the mutation's onError
      setShowDeleteConfirm(false)
    }
  }

  const handleDeleteCancel = () => {
    setShowDeleteConfirm(false)
  }

  return (
    <>
      <Drawer
        open={open}
        onClose={onClose}
        title={host.name}
        width="w-[600px]"
      >
      {/* Expand Button - positioned next to close button */}
      {onExpand && (
        <div className="absolute top-6 right-16 z-10">
          <button
            onClick={() => onExpand(hostId)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent hover:bg-accent/90 text-accent-foreground transition-colors text-sm"
          >
            <Maximize2 className="h-4 w-4" />
            <span>Expand</span>
          </button>
        </div>
      )}

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

          <div className="flex-1" />

          <button
            onClick={handleDeleteClick}
            disabled={deleteMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-500 border border-red-500/20 transition-colors text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Trash2 className="h-4 w-4" />
            <span>{deleteMutation.isPending ? 'Deleting...' : 'Delete'}</span>
          </button>
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

    {/* Delete Confirmation Dialog */}
    {showDeleteConfirm && (
      <div className="fixed inset-0 bg-black/70 z-[60] flex items-center justify-center p-4">
        <div className="bg-surface border border-border rounded-lg shadow-2xl max-w-md w-full p-6">
          <div className="flex items-start gap-4 mb-4">
            <div className="flex-shrink-0 w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center">
              <AlertTriangle className="h-6 w-6 text-red-500" />
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-semibold mb-2">Delete Host</h3>
              <p className="text-sm text-muted-foreground">
                Are you sure you want to delete <span className="font-semibold text-foreground">{host.name}</span>? This action cannot be undone.
              </p>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              onClick={handleDeleteCancel}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 rounded-lg border border-border bg-background hover:bg-muted transition-colors text-sm disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleDeleteConfirm}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 rounded-lg bg-red-500 hover:bg-red-600 text-white transition-colors text-sm disabled:opacity-50"
            >
              {deleteMutation.isPending ? 'Deleting...' : 'Delete Host'}
            </button>
          </div>
        </div>
      </div>
    )}
  </>
  )
}
