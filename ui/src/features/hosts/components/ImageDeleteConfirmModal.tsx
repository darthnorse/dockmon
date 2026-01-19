/**
 * ImageDeleteConfirmModal Component
 *
 * Confirmation modal for deleting Docker images
 * Shows warning for in-use images and force delete option
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { AlertTriangle } from 'lucide-react'
import { ConfirmModal } from '@/components/shared/ConfirmModal'
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

  const handleConfirm = useCallback(() => {
    onConfirm(forceDelete)
  }, [onConfirm, forceDelete])

  // Check if any images are in use
  const inUseImages = useMemo(() => images.filter((img) => img.in_use), [images])
  const hasInUseImages = inUseImages.length > 0

  // Calculate total size
  const totalSize = useMemo(() => images.reduce((acc, img) => acc + img.size, 0), [images])

  const imageCount = images.length
  const confirmText = `Delete ${imageCount} Image${imageCount !== 1 ? 's' : ''}`

  return (
    <ConfirmModal
      isOpen={isOpen}
      onClose={onClose}
      onConfirm={handleConfirm}
      title={`Delete Image${imageCount !== 1 ? 's' : ''}`}
      description="This action cannot be undone."
      confirmText={confirmText}
      pendingText="Deleting..."
      variant="danger"
      isPending={isPending}
      disabled={hasInUseImages && !forceDelete}
    >
      <div className="space-y-4">
        {/* Warning for in-use images */}
        {hasInUseImages && (
          <div className="flex items-start gap-3 p-3 bg-warning/10 border border-warning/30 rounded-lg">
            <AlertTriangle className="h-5 w-5 text-warning flex-shrink-0 mt-0.5" aria-hidden="true" />
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
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {images.map((image) => (
            <div
              key={image.id}
              className="flex items-center gap-3 p-2 rounded bg-surface-2"
            >
              <div
                className={`h-2 w-2 rounded-full flex-shrink-0 ${getStatusDotColor(image)}`}
                aria-hidden="true"
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
    </ConfirmModal>
  )
}
