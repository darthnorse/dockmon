/**
 * HostImagesTab Component
 *
 * Images tab for host modal - shows Docker images with bulk deletion
 */

import { useState, useMemo, useCallback, useEffect, useDeferredValue } from 'react'
import { Search, Trash2, Filter, AlertTriangle, Box } from 'lucide-react'
import { useHostImages, usePruneImages, useDeleteImages } from '../../hooks/useHostImages'
import { ImageDeleteConfirmModal } from '../ImageDeleteConfirmModal'
import { ConfirmModal } from '@/components/shared/ConfirmModal'
import { StatusBadge } from '@/components/shared/StatusBadge'
import { ContainerLinkList } from '@/components/shared/ContainerLinkList'
import { formatBytes, pluralize } from '@/lib/utils/formatting'
import { formatRelativeTime } from '@/lib/utils/eventUtils'
import { getImageDisplayName, makeImageCompositeKey } from '@/lib/utils/image'
import type { DockerImage } from '@/types/api'

interface HostImagesTabProps {
  hostId: string
}

function ImageStatusBadge({ image }: { image: DockerImage }) {
  if (image.in_use) {
    return (
      <StatusBadge variant="success">
        In Use ({image.container_count})
      </StatusBadge>
    )
  }
  if (image.dangling) {
    return (
      <StatusBadge variant="warning" icon={<AlertTriangle className="h-3 w-3" />}>
        Dangling
      </StatusBadge>
    )
  }
  return (
    <StatusBadge variant="muted">
      Unused
    </StatusBadge>
  )
}

export function HostImagesTab({ hostId }: HostImagesTabProps) {
  const { data: images, isLoading, error } = useHostImages(hostId)
  const pruneMutation = usePruneImages(hostId)
  const deleteMutation = useDeleteImages()

  // UI state
  const [searchQuery, setSearchQuery] = useState('')
  const deferredSearchQuery = useDeferredValue(searchQuery)
  const [showUnusedOnly, setShowUnusedOnly] = useState(false)
  const [selectedImageIds, setSelectedImageIds] = useState<Set<string>>(new Set())
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [imagesToDelete, setImagesToDelete] = useState<DockerImage[]>([])
  const [showPruneConfirm, setShowPruneConfirm] = useState(false)

  // Filter images (using deferred search to prevent jank on large lists)
  const filteredImages = useMemo(() => {
    if (!images) return []

    return images.filter((image) => {
      // Apply unused filter
      if (showUnusedOnly && image.in_use) return false

      // Apply search filter (search in tags and ID)
      if (deferredSearchQuery) {
        const query = deferredSearchQuery.toLowerCase()
        const matchesTags = image.tags.some((tag) => tag.toLowerCase().includes(query))
        const matchesId = image.id.toLowerCase().includes(query)
        if (!matchesTags && !matchesId) return false
      }

      return true
    })
  }, [images, showUnusedOnly, deferredSearchQuery])

  // Memoize all image keys (for cleaning up stale selections)
  const allImageKeys = useMemo(
    () => new Set((images ?? []).map((img) => makeImageCompositeKey(hostId, img.id))),
    [images, hostId]
  )

  // Clean up stale selections when images change (e.g., after deletion)
  useEffect(() => {
    setSelectedImageIds((prev) => {
      const validKeys = new Set([...prev].filter((key) => allImageKeys.has(key)))
      // Only update if something was removed
      if (validKeys.size !== prev.size) {
        return validKeys
      }
      return prev
    })
  }, [allImageKeys])

  // Memoize current composite keys to avoid duplicate computation
  const currentKeys = useMemo(
    () => filteredImages.map((img) => makeImageCompositeKey(hostId, img.id)),
    [filteredImages, hostId]
  )

  // Check if all current images are selected
  const allSelected = useMemo(
    () => currentKeys.length > 0 && currentKeys.every((key) => selectedImageIds.has(key)),
    [currentKeys, selectedImageIds]
  )

  // Toggle selection for a single image
  const toggleImageSelection = useCallback((imageId: string) => {
    setSelectedImageIds((prev) => {
      const next = new Set(prev)
      const compositeKey = makeImageCompositeKey(hostId, imageId)
      if (next.has(compositeKey)) {
        next.delete(compositeKey)
      } else {
        next.add(compositeKey)
      }
      return next
    })
  }, [hostId])

  // Toggle select all (for current filtered view)
  const toggleSelectAll = useCallback(() => {
    if (allSelected) {
      // Deselect all current
      setSelectedImageIds((prev) => {
        const next = new Set(prev)
        currentKeys.forEach((key) => next.delete(key))
        return next
      })
    } else {
      // Select all current
      setSelectedImageIds((prev) => {
        const next = new Set(prev)
        currentKeys.forEach((key) => next.add(key))
        return next
      })
    }
  }, [allSelected, currentKeys])

  // Handle delete button click (single image)
  const handleDeleteClick = useCallback((image: DockerImage) => {
    setImagesToDelete([image])
    setDeleteModalOpen(true)
  }, [])

  // Handle bulk delete button click
  const handleBulkDeleteClick = useCallback(() => {
    if (!images) return
    const selected = images.filter((img) => selectedImageIds.has(makeImageCompositeKey(hostId, img.id)))
    setImagesToDelete(selected)
    setDeleteModalOpen(true)
  }, [images, selectedImageIds, hostId])

  // Handle delete confirmation
  const handleDeleteConfirm = useCallback((force: boolean) => {
    const imageIds = imagesToDelete.map((img) => makeImageCompositeKey(hostId, img.id))
    const imageNames: Record<string, string> = {}
    imagesToDelete.forEach((img) => {
      imageNames[makeImageCompositeKey(hostId, img.id)] = getImageDisplayName(img)
    })

    deleteMutation.mutate({
      hostId,
      imageIds,
      imageNames,
      force,
    }, {
      onSuccess: () => {
        setDeleteModalOpen(false)
        setImagesToDelete([])
        // Clear selection for deleted images
        setSelectedImageIds((prev) => {
          const next = new Set(prev)
          imageIds.forEach((id) => next.delete(id))
          return next
        })
      },
    })
  }, [imagesToDelete, hostId, deleteMutation])

  // Count of selected images
  const selectedCount = selectedImageIds.size

  // Count of unused images
  const unusedCount = useMemo(() => {
    return images?.filter((img) => !img.in_use).length ?? 0
  }, [images])

  // Handle prune confirmation
  const handlePruneConfirm = useCallback(() => {
    pruneMutation.mutate(undefined, {
      onSuccess: () => {
        setShowPruneConfirm(false)
        setSelectedImageIds(new Set())
      },
      onError: () => setShowPruneConfirm(false),
    })
  }, [pruneMutation])

  const handlePruneClose = useCallback(() => {
    setShowPruneConfirm(false)
  }, [])

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
          Failed to load images: {error.message}
        </div>
      </div>
    )
  }

  // Empty state
  if (!images || images.length === 0) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <Box className="h-12 w-12 mx-auto mb-3 opacity-50" />
        No images found on this host.
      </div>
    )
  }

  return (
    <div className={`p-6 space-y-4 ${selectedCount > 0 ? 'pb-32' : ''}`}>
      {/* Header with search and actions */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search images..."
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

          {/* Prune button */}
          <button
            onClick={() => setShowPruneConfirm(true)}
            disabled={pruneMutation.isPending || unusedCount === 0}
            className="flex items-center gap-2 px-3 py-2 text-sm rounded-lg bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Trash2 className="h-4 w-4" />
            Prune All Unused
          </button>
        </div>
      </div>

      {/* Image count */}
      <div className="text-sm text-muted-foreground">
        Showing {filteredImages.length} of {images.length} images
        {selectedCount > 0 && (
          <span className="ml-2 text-accent">({selectedCount} selected)</span>
        )}
      </div>

      {/* Images table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead className="bg-surface-2 border-b border-border">
            <tr>
              <th className="w-10 p-3">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleSelectAll}
                  className="w-4 h-4 rounded border-border cursor-pointer"
                />
              </th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Image</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden md:table-cell">Size</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden lg:table-cell">Created</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground">Status</th>
              <th className="text-left p-3 text-sm font-medium text-muted-foreground hidden xl:table-cell">Containers</th>
              <th className="w-20 p-3 text-sm font-medium text-muted-foreground">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filteredImages.map((image) => {
              const compositeKey = makeImageCompositeKey(hostId, image.id)
              const isSelected = selectedImageIds.has(compositeKey)

              return (
                <tr
                  key={compositeKey}
                  className={`hover:bg-surface-2 transition-colors ${isSelected ? 'bg-accent/5' : ''}`}
                >
                  <td className="p-3">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleImageSelection(image.id)}
                      className="w-4 h-4 rounded border-border cursor-pointer"
                    />
                  </td>
                  <td className="p-3">
                    <div className="space-y-1">
                      {image.tags.length > 0 ? (
                        image.tags.map((tag, idx) => (
                          <div key={idx} className="text-sm font-mono">
                            {tag}
                          </div>
                        ))
                      ) : (
                        <div className="text-sm text-muted-foreground font-mono">
                          &lt;none&gt;
                        </div>
                      )}
                      <div className="text-xs text-muted-foreground font-mono">
                        {image.id}
                      </div>
                    </div>
                  </td>
                  <td className="p-3 hidden md:table-cell">
                    <span className="text-sm">{formatBytes(image.size)}</span>
                  </td>
                  <td className="p-3 hidden lg:table-cell">
                    <span className="text-sm text-muted-foreground">
                      {formatRelativeTime(image.created)}
                    </span>
                  </td>
                  <td className="p-3">
                    <ImageStatusBadge image={image} />
                  </td>
                  <td className="p-3 hidden xl:table-cell">
                    <ContainerLinkList containers={image.containers} hostId={hostId} />
                  </td>
                  <td className="p-3">
                    <button
                      onClick={() => handleDeleteClick(image)}
                      className="p-2 rounded-lg hover:bg-danger/10 text-danger/70 hover:text-danger transition-colors"
                      title="Delete image"
                      aria-label={`Delete image ${image.tags[0] || image.id}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Empty filtered state */}
      {filteredImages.length === 0 && images.length > 0 && (
        <div className="text-center text-muted-foreground py-8">
          No images match your filters.
        </div>
      )}

      {/* Bulk action bar */}
      {selectedCount > 0 && (
        <div className="fixed bottom-0 left-0 right-0 z-40 bg-surface-1 border-t border-border p-4 shadow-lg">
          <div className="max-w-screen-xl mx-auto flex items-center justify-between">
            <div className="text-sm">
              <span className="font-medium">{selectedCount}</span>
              {' '}{pluralize(selectedCount, 'image')} selected
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setSelectedImageIds(new Set())}
                className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Clear Selection
              </button>
              <button
                onClick={handleBulkDeleteClick}
                disabled={deleteMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 text-sm rounded-lg bg-danger text-danger-foreground hover:bg-danger/90 disabled:opacity-50 transition-colors"
              >
                <Trash2 className="h-4 w-4" />
                Delete Selected
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      <ImageDeleteConfirmModal
        isOpen={deleteModalOpen}
        onClose={() => {
          setDeleteModalOpen(false)
          setImagesToDelete([])
        }}
        onConfirm={handleDeleteConfirm}
        images={imagesToDelete}
        isPending={deleteMutation.isPending}
      />

      <ConfirmModal
        isOpen={showPruneConfirm}
        onClose={handlePruneClose}
        onConfirm={handlePruneConfirm}
        title="Prune Unused Images"
        description={`This will remove ${unusedCount} unused ${pluralize(unusedCount, 'image')}.`}
        confirmText="Prune Images"
        pendingText="Pruning..."
        variant="warning"
        isPending={pruneMutation.isPending}
      >
        <p className="text-sm text-muted-foreground">
          Images that are not used by any containers will be permanently deleted.
          This includes dangling images (untagged layers).
        </p>
      </ConfirmModal>
    </div>
  )
}
