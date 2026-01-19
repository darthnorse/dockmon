/**
 * NetworkDeleteConfirmModal Component
 *
 * Confirmation modal for deleting Docker networks
 * Shows warning for networks with connected containers and force delete option
 */

import { useState, useEffect } from 'react'
import { AlertTriangle } from 'lucide-react'
import { pluralize } from '@/lib/utils/formatting'
import type { DockerNetwork } from '@/types/api'

interface NetworkDeleteConfirmModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (force: boolean) => void
  network: DockerNetwork | null
  isPending?: boolean
}

export function NetworkDeleteConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  network,
  isPending = false,
}: NetworkDeleteConfirmModalProps) {
  const [forceDelete, setForceDelete] = useState(false)

  // Reset forceDelete when modal opens with new network
  useEffect(() => {
    if (isOpen) {
      setForceDelete(false)
    }
  }, [isOpen])

  if (!isOpen || !network) return null

  // Check if network has connected containers
  const hasConnectedContainers = network.container_count > 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-surface-1 rounded-lg shadow-xl border border-border max-w-md w-full mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center h-8 w-8 rounded-full bg-danger/10">
              <AlertTriangle className="h-5 w-5 text-danger" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">
                Delete Network
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                This action cannot be undone.
              </p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-4 overflow-y-auto flex-1 space-y-4">
          {/* Warning for networks with connected containers */}
          {hasConnectedContainers && (
            <div className="flex items-start gap-3 p-3 bg-warning/10 border border-warning/30 rounded-lg">
              <AlertTriangle className="h-5 w-5 text-warning flex-shrink-0 mt-0.5" />
              <div className="text-sm">
                <p className="font-medium text-warning">
                  Network has {network.container_count} connected {pluralize(network.container_count, 'container')}
                </p>
                <p className="text-muted-foreground mt-1">
                  Deleting this network requires disconnecting all containers first.
                  This may affect container networking.
                </p>
              </div>
            </div>
          )}

          {/* Network info */}
          <div className="p-3 rounded bg-surface-2 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Name</span>
              <span className="text-sm font-medium text-foreground font-mono">
                {network.name}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Driver</span>
              <span className="text-sm text-foreground">
                {network.driver || 'default'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Scope</span>
              <span className="text-sm text-foreground">
                {network.scope}
              </span>
            </div>
            {hasConnectedContainers && (
              <div className="pt-2 border-t border-border">
                <span className="text-sm text-muted-foreground">Connected containers:</span>
                <ul className="mt-1 space-y-1">
                  {network.containers.slice(0, 5).map((container) => (
                    <li key={container.id} className="text-sm text-foreground font-mono pl-2">
                      {container.name || container.id}
                    </li>
                  ))}
                  {network.containers.length > 5 && (
                    <li className="text-sm text-muted-foreground pl-2">
                      ...and {network.containers.length - 5} more
                    </li>
                  )}
                </ul>
              </div>
            )}
          </div>

          {/* Force delete option (only show if there are connected containers) */}
          {hasConnectedContainers && (
            <div className="border-t border-border pt-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={forceDelete}
                  onChange={(e) => setForceDelete(e.target.checked)}
                  className="w-4 h-4 rounded border-border"
                />
                <span className="text-sm text-foreground">
                  Force delete (disconnect containers first)
                </span>
              </label>
              <p className="text-xs text-warning mt-2">
                Warning: Force deleting will disconnect all containers from this network.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            disabled={isPending}
            className="px-4 py-2 text-sm font-medium text-foreground hover:bg-surface-2 rounded transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(forceDelete)}
            disabled={isPending || (hasConnectedContainers && !forceDelete)}
            className="px-4 py-2 text-sm font-medium rounded transition-colors bg-danger text-danger-foreground hover:bg-danger/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isPending ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
                Deleting...
              </span>
            ) : (
              'Delete Network'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
