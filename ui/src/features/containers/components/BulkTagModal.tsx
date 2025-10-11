/**
 * BulkTagModal - Modal for bulk tag operations
 *
 * Allows adding or removing tags from multiple containers
 * Uses batch job API for reliable bulk operations
 */

import { useState, KeyboardEvent } from 'react'
import { X, Plus, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface BulkTagModalProps {
  isOpen: boolean
  onClose: () => void
  mode: 'add' | 'remove'
  selectedContainers: Array<{
    id: string
    host_id: string
    name: string
    tags: string[]
  }>
  onConfirm: (tags: string[]) => Promise<void>
}

export function BulkTagModal({ isOpen, onClose, mode, selectedContainers, onConfirm }: BulkTagModalProps) {
  const [tags, setTags] = useState<string[]>([])
  const [inputValue, setInputValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (!isOpen) return null

  const validateTag = (tag: string): { valid: boolean; error?: string } => {
    if (!tag || !tag.trim()) {
      return { valid: false, error: 'Tag cannot be empty' }
    }

    if (tag.length > 50) {
      return { valid: false, error: 'Tag cannot exceed 50 characters' }
    }

    // Allow alphanumeric + dash, underscore, colon, dot
    const validPattern = /^[a-zA-Z0-9\-_:.]+$/
    if (!validPattern.test(tag)) {
      return { valid: false, error: 'Tag can only contain alphanumeric characters, dash, underscore, colon, and dot' }
    }

    const normalizedTag = tag.toLowerCase()
    if (tags.map(t => t.toLowerCase()).includes(normalizedTag)) {
      return { valid: false, error: 'Tag already in list' }
    }

    return { valid: true }
  }

  const handleAddTag = () => {
    const tag = inputValue.trim()

    const validation = validateTag(tag)
    if (!validation.valid) {
      setError(validation.error || 'Invalid tag')
      return
    }

    const normalizedTag = tag.toLowerCase()
    setTags([...tags, normalizedTag])
    setInputValue('')
    setError(null)
  }

  const handleRemoveTag = (tagToRemove: string) => {
    setTags(tags.filter(t => t !== tagToRemove))
  }

  const handleKeyPress = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleAddTag()
    } else if (e.key === 'Escape') {
      setInputValue('')
      setError(null)
    }
  }

  const handleSubmit = async () => {
    if (tags.length === 0) {
      setError('Please add at least one tag')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      await onConfirm(tags)
      // Reset form on success
      setTags([])
      setInputValue('')
      onClose()
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to update tags'
      setError(errorMessage)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleClose = () => {
    if (!isSubmitting) {
      setTags([])
      setInputValue('')
      setError(null)
      onClose()
    }
  }

  // For "remove" mode, show common tags across selected containers
  const commonTags = mode === 'remove'
    ? selectedContainers.reduce((acc, container) => {
        if (acc.length === 0 && container.tags) {
          return container.tags.filter(tag => !tag.startsWith('compose:') && !tag.startsWith('swarm:'))
        }
        return acc.filter(tag => container.tags?.includes(tag))
      }, [] as string[])
    : []

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 z-50"
        onClick={handleClose}
      />

      {/* Modal */}
      <div className="fixed inset-0 flex items-center justify-center z-50 p-4">
        <div className="bg-surface-1 rounded-lg shadow-xl max-w-md w-full max-h-[90vh] overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between p-4 border-b border-border">
            <h2 className="text-lg font-semibold text-foreground">
              {mode === 'add' ? 'Add Tags' : 'Remove Tags'}
            </h2>
            <button
              onClick={handleClose}
              disabled={isSubmitting}
              className="text-muted-foreground hover:text-foreground transition-colors p-1"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Body */}
          <div className="p-4 space-y-4 overflow-y-auto max-h-[60vh]">
            {/* Info */}
            <div className="flex items-start gap-2 p-3 bg-info/10 text-info rounded">
              <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <p className="text-sm">
                {mode === 'add'
                  ? `Add tags to ${selectedContainers.length} container${selectedContainers.length !== 1 ? 's' : ''}. Tags will be merged with existing tags.`
                  : `Remove tags from ${selectedContainers.length} container${selectedContainers.length !== 1 ? 's' : ''}. Only custom tags can be removed.`
                }
              </p>
            </div>

            {/* For Remove mode: Show common tags to choose from */}
            {mode === 'remove' && commonTags.length > 0 && (
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">Common tags across selected containers:</label>
                <div className="flex flex-wrap gap-2">
                  {commonTags.map((tag) => (
                    <button
                      key={tag}
                      onClick={() => {
                        if (!tags.includes(tag)) {
                          setTags([...tags, tag])
                        }
                      }}
                      disabled={tags.includes(tag)}
                      className={`px-2 py-1 rounded text-xs transition-colors ${
                        tags.includes(tag)
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted text-foreground hover:bg-muted/80'
                      }`}
                    >
                      {tag}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Input field */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">
                {mode === 'add' ? 'Add tags:' : 'Tags to remove:'}
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => {
                    setInputValue(e.target.value)
                    setError(null)
                  }}
                  onKeyDown={handleKeyPress}
                  placeholder="Enter tag name..."
                  disabled={isSubmitting}
                  className="flex-1 px-3 py-2 text-sm border border-border rounded bg-background focus:outline-none focus:ring-2 focus:ring-primary"
                />
                <Button
                  onClick={handleAddTag}
                  disabled={isSubmitting || !inputValue.trim()}
                  size="sm"
                  variant="outline"
                >
                  <Plus className="w-4 h-4" />
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Press Enter to add, or click the + button
              </p>
            </div>

            {/* Tag list */}
            {tags.length > 0 && (
              <div className="space-y-2">
                <label className="text-sm font-medium text-foreground">
                  Tags to {mode === 'add' ? 'add' : 'remove'}:
                </label>
                <div className="flex flex-wrap gap-2 p-3 bg-muted/20 rounded min-h-[48px]">
                  {tags.map((tag) => (
                    <div
                      key={tag}
                      className="inline-flex items-center gap-1 px-2 py-1 bg-primary/10 text-primary rounded text-xs"
                    >
                      <span>{tag}</span>
                      <button
                        onClick={() => handleRemoveTag(tag)}
                        disabled={isSubmitting}
                        className="hover:bg-black/10 dark:hover:bg-white/10 rounded p-0.5 transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Error message */}
            {error && (
              <div className="flex items-start gap-2 p-3 bg-danger/10 text-danger rounded">
                <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <p className="text-sm">{error}</p>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 p-4 border-t border-border">
            <Button
              variant="ghost"
              onClick={handleClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={isSubmitting || tags.length === 0}
            >
              {isSubmitting ? 'Processing...' : mode === 'add' ? 'Add Tags' : 'Remove Tags'}
            </Button>
          </div>
        </div>
      </div>
    </>
  )
}
