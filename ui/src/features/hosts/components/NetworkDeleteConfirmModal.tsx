/**
 * NetworkDeleteConfirmModal Component
 *
 * Confirmation modal for deleting Docker networks (single or bulk)
 * Shows warning for networks with connected containers and force delete option
 */

import { useState, useEffect, useCallback } from 'react'
import { AlertTriangle } from 'lucide-react'
import { ConfirmModal } from '@/components/shared/ConfirmModal'
import { pluralize } from '@/lib/utils/formatting'
import type { DockerNetwork } from '@/types/api'

interface NetworkDeleteConfirmModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (force: boolean) => void
  network: DockerNetwork | null  // Single network for single delete
  networkCount?: number          // Total count for bulk delete
  isPending?: boolean
}

export function NetworkDeleteConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  network,
  networkCount = 1,
  isPending = false,
}: NetworkDeleteConfirmModalProps) {
  const [forceDelete, setForceDelete] = useState(false)

  // Reset forceDelete when modal opens
  useEffect(() => {
    if (isOpen) {
      setForceDelete(false)
    }
  }, [isOpen])

  const handleConfirm = useCallback(() => {
    onConfirm(forceDelete)
  }, [onConfirm, forceDelete])

  // Bulk delete mode
  if (networkCount > 1) {
    return (
      <ConfirmModal
        isOpen={isOpen}
        onClose={onClose}
        onConfirm={handleConfirm}
        title="Delete Networks"
        description={`Delete ${networkCount} selected networks? This action cannot be undone.`}
        confirmText={`Delete ${networkCount} Networks`}
        pendingText="Deleting..."
        variant="danger"
        isPending={isPending}
      >
        <div className="space-y-4">
          <div className="flex items-start gap-3 p-3 bg-warning/10 border border-warning/30 rounded-lg">
            <AlertTriangle className="h-5 w-5 text-warning flex-shrink-0 mt-0.5" aria-hidden="true" />
            <div className="text-sm">
              <p className="font-medium text-warning">
                Bulk network deletion
              </p>
              <p className="text-muted-foreground mt-1">
                Networks with connected containers will require force delete.
              </p>
            </div>
          </div>

          <div className="border-t border-border pt-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={forceDelete}
                onChange={(e) => setForceDelete(e.target.checked)}
                className="w-4 h-4 rounded border-border"
              />
              <span className="text-sm text-foreground">
                Force delete (disconnect containers if needed)
              </span>
            </label>
          </div>
        </div>
      </ConfirmModal>
    )
  }

  // Single delete mode
  if (!network) return null

  const hasConnectedContainers = network.container_count > 0

  return (
    <ConfirmModal
      isOpen={isOpen}
      onClose={onClose}
      onConfirm={handleConfirm}
      title="Delete Network"
      description="This action cannot be undone."
      confirmText="Delete Network"
      pendingText="Deleting..."
      variant="danger"
      isPending={isPending}
      disabled={hasConnectedContainers && !forceDelete}
    >
      <div className="space-y-4">
        {/* Warning for networks with connected containers */}
        {hasConnectedContainers && (
          <div className="flex items-start gap-3 p-3 bg-warning/10 border border-warning/30 rounded-lg">
            <AlertTriangle className="h-5 w-5 text-warning flex-shrink-0 mt-0.5" aria-hidden="true" />
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
    </ConfirmModal>
  )
}
