/**
 * Delete Container Dialog
 *
 * Confirmation dialog for container deletion with:
 * - Enhanced warning for protected containers (databases, proxies, monitoring)
 * - Optional volume removal checkbox
 * - Clear messaging about what gets deleted
 * - DockMon self-protection (handled by backend)
 */

import { useState } from 'react'
import { AlertTriangle, Database, Network, Activity, Shield, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface DeleteContainerDialogProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (removeVolumes: boolean) => void
  containerName: string
  containerImage: string
  isDockMon: boolean
}

/**
 * Detect if container is "protected" based on image name patterns
 * Matches the same patterns as update validation system
 */
function detectProtectedContainer(image: string): {
  isProtected: boolean
  category?: 'databases' | 'proxies' | 'monitoring' | 'critical'
  icon: typeof AlertTriangle
  iconColor: string
  reason: string
} {
  const imageLower = image.toLowerCase()

  // Database containers
  if (
    imageLower.includes('postgres') ||
    imageLower.includes('mysql') ||
    imageLower.includes('mariadb') ||
    imageLower.includes('mongodb') ||
    imageLower.includes('redis') ||
    imageLower.includes('cassandra') ||
    imageLower.includes('elasticsearch') ||
    imageLower.includes('influxdb')
  ) {
    return {
      isProtected: true,
      category: 'databases',
      icon: Database,
      iconColor: 'text-blue-400',
      reason: 'This appears to be a database container. Deleting it may result in data loss.',
    }
  }

  // Proxy/reverse proxy containers
  if (
    imageLower.includes('nginx') ||
    imageLower.includes('traefik') ||
    imageLower.includes('caddy') ||
    imageLower.includes('haproxy') ||
    imageLower.includes('envoy')
  ) {
    return {
      isProtected: true,
      category: 'proxies',
      icon: Network,
      iconColor: 'text-purple-400',
      reason: 'This appears to be a proxy/reverse proxy. Deleting it may affect network routing.',
    }
  }

  // Monitoring/logging containers
  if (
    imageLower.includes('prometheus') ||
    imageLower.includes('grafana') ||
    imageLower.includes('loki') ||
    imageLower.includes('jaeger') ||
    imageLower.includes('datadog') ||
    imageLower.includes('newrelic')
  ) {
    return {
      isProtected: true,
      category: 'monitoring',
      icon: Activity,
      iconColor: 'text-green-400',
      reason: 'This appears to be a monitoring/logging container. Deleting it may affect observability.',
    }
  }

  // Not protected
  return {
    isProtected: false,
    icon: AlertTriangle,
    iconColor: 'text-yellow-400',
    reason: '',
  }
}

export function DeleteContainerDialog({
  isOpen,
  onClose,
  onConfirm,
  containerName,
  containerImage,
  isDockMon,
}: DeleteContainerDialogProps) {
  const [removeVolumes, setRemoveVolumes] = useState(false)
  const protectionInfo = detectProtectedContainer(containerImage)

  if (!isOpen) return null

  const handleConfirm = () => {
    onConfirm(removeVolumes)
    onClose()
  }

  // Prevent event bubbling to backdrop
  const handleModalClick = (e: React.MouseEvent) => {
    e.stopPropagation()
  }

  // DockMon self-protection warning (should never happen, but defensive UI)
  if (isDockMon) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div
          className="absolute inset-0 bg-black/50 backdrop-blur-sm"
          onClick={onClose}
          aria-hidden="true"
        />

        <div
          className="relative bg-surface-1 rounded-lg shadow-xl border border-border max-w-md w-full"
          onClick={handleModalClick}
          role="dialog"
          aria-modal="true"
        >
          <div className="p-6">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 text-red-400">
                <Shield className="w-6 h-6" />
              </div>
              <div className="flex-1">
                <h2 className="text-lg font-semibold text-text-primary">
                  Cannot Delete DockMon
                </h2>
                <p className="mt-2 text-sm text-text-secondary">
                  DockMon cannot delete itself. If you need to remove DockMon, please stop and
                  remove the container manually via Docker CLI or another management tool.
                </p>
              </div>
            </div>
          </div>

          <div className="px-6 py-4 bg-surface-2 rounded-b-lg border-t border-border flex justify-end">
            <Button variant="outline" onClick={onClose} className="min-w-[100px]">
              Close
            </Button>
          </div>
        </div>
      </div>
    )
  }

  const Icon = protectionInfo.icon
  const iconColor = protectionInfo.iconColor

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      data-testid="delete-container-dialog"
    >
      {/* Backdrop - clickable to close */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal Container */}
      <div
        className="relative bg-surface-1 rounded-lg shadow-xl border border-border max-w-md w-full"
        onClick={handleModalClick}
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-modal-title"
      >
        {/* Header */}
        <div className="p-6 pb-4">
          <div className="flex items-start gap-4">
            <div className={`flex-shrink-0 ${iconColor}`}>
              <Icon className="w-6 h-6" />
            </div>
            <div className="flex-1">
              <h2 id="delete-modal-title" className="text-lg font-semibold text-text-primary">
                {protectionInfo.isProtected ? 'Confirm Deletion of Protected Container' : 'Delete Container'}
              </h2>
              <p className="mt-1 text-sm text-text-secondary">{containerName}</p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 pb-4">
          {/* Protection Warning */}
          {protectionInfo.isProtected && (
            <div className="bg-surface-2 rounded-md p-4 border border-border/50 mb-4">
              <p className="text-sm text-text-secondary mb-2">
                <strong className="text-text-primary">Warning:</strong> {protectionInfo.reason}
              </p>
              <p className="text-xs text-text-tertiary">
                Please ensure you have backups and understand the impact of deleting this container.
              </p>
            </div>
          )}

          {/* Standard confirmation message */}
          <div className="mb-4">
            <p className="text-sm text-text-secondary">
              Are you sure you want to delete <strong className="text-text-primary">{containerName}</strong>?
            </p>
            <p className="text-xs text-text-tertiary mt-2">
              This action will permanently remove the container. This cannot be undone.
            </p>
          </div>

          {/* Volume removal option */}
          <div className="bg-surface-2 rounded-md p-4 border border-border/50">
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={removeVolumes}
                onChange={(e) => setRemoveVolumes(e.target.checked)}
                className="mt-0.5 w-4 h-4 rounded border-border bg-surface-3 text-primary focus:ring-2 focus:ring-primary focus:ring-offset-0"
              />
              <div className="flex-1">
                <span className="text-sm text-text-primary font-medium">
                  Also remove anonymous volumes
                </span>
                <p className="text-xs text-text-tertiary mt-1">
                  This will delete unnamed volumes associated with this container. Named volumes
                  will always be preserved.
                </p>
              </div>
            </label>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-surface-2 rounded-b-lg border-t border-border flex justify-end gap-3">
          <Button variant="outline" onClick={onClose} className="min-w-[100px]">
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            className="min-w-[100px] bg-red-600 hover:bg-red-700 text-white"
          >
            <Trash2 className="w-4 h-4 mr-2" />
            Delete
          </Button>
        </div>
      </div>
    </div>
  )
}
