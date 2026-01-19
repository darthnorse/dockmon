/**
 * ImageDeleteConfirmModal Component
 *
 * Confirmation modal for deleting Docker images
 * Shows warning for in-use images and force delete option
 */

import { useState, useEffect } from 'react'
import { AlertTriangle } from 'lucide-react'
import type { DockerImage } from '@/types/api'
import { formatBytes } from '@/lib/utils/formatting'
import { getImageDisplayName } from '@/lib/utils/image'

interface ImageDeleteConfirmModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (force: boolean) => void
  images: DockerImage[]
  isPending?: boolean
}

/**
 * Get the status dot color class for an image
 */
function getStatusDotColor(image: DockerImage): string {
  if (image.in_use) return 'bg-success'
  if (image.dangling) return 'bg-warning'
  return 'bg-muted-foreground'
}

export function ImageDeleteConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  images,
  isPending = false,
}: ImageDeleteConfirmModalProps) {
  const [forceDelete, setForceDelete] = useState(false)

  // Reset forceDelete when modal opens with new images
  useEffect(() => {
    if (isOpen) {
      setForceDelete(false)
    }
  }, [isOpen])

  if (!isOpen) return null

  // Check if any images are in use
  const inUseImages = images.filter((img) => img.in_use)
  const hasInUseImages = inUseImages.length > 0

  // Calculate total size
  const totalSize = images.reduce((acc, img) => acc + img.size, 0)

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
                Delete Image{images.length !== 1 ? 's' : ''}
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                This action cannot be undone.
              </p>
            </div>
          </div>
        </div>

        {/* Image List */}
        <div className="px-6 py-4 overflow-y-auto flex-1 space-y-4">
          {/* Warning for in-use images */}
          {hasInUseImages && (
            <div className="flex items-start gap-3 p-3 bg-warning/10 border border-warning/30 rounded-lg">
              <AlertTriangle className="h-5 w-5 text-warning flex-shrink-0 mt-0.5" />
              <div className="text-sm">
                <p className="font-medium text-warning">
                  {inUseImages.length} image{inUseImages.length !== 1 ? 's are' : ' is'} in use
                </p>
                <p className="text-muted-foreground mt-1">
                  Deleting images that are in use by containers requires force delete.
                  This may cause containers to fail if they are restarted.
                </p>
              </div>
            </div>
          )}

          {/* Image list */}
          <div className="space-y-2">
            {images.map((image) => (
              <div
                key={image.id}
                className="flex items-center gap-3 p-2 rounded bg-surface-2"
              >
                <div
                  className={`h-2 w-2 rounded-full flex-shrink-0 ${getStatusDotColor(image)}`}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-foreground truncate font-mono">
                    {getImageDisplayName(image)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {formatBytes(image.size)}
                    {image.in_use && (
                      <span className="ml-2 text-success">
                        In use by {image.container_count} container{image.container_count !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Total size */}
          <div className="text-sm text-muted-foreground border-t border-border pt-3">
            Total size: <span className="font-medium text-foreground">{formatBytes(totalSize)}</span>
          </div>

          {/* Force delete option (only show if there are in-use images) */}
          {hasInUseImages && (
            <div className="border-t border-border pt-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={forceDelete}
                  onChange={(e) => setForceDelete(e.target.checked)}
                  className="w-4 h-4 rounded border-border"
                />
                <span className="text-sm text-foreground">
                  Force delete (remove even if in use)
                </span>
              </label>
              <p className="text-xs text-warning mt-2">
                Warning: Force deleting in-use images may cause containers to fail on restart.
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
            disabled={isPending || (hasInUseImages && !forceDelete)}
            className="px-4 py-2 text-sm font-medium rounded transition-colors bg-danger text-danger-foreground hover:bg-danger/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isPending ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin h-4 w-4 border-2 border-current border-t-transparent rounded-full" />
                Deleting...
              </span>
            ) : (
              `Delete ${images.length} Image${images.length !== 1 ? 's' : ''}`
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
