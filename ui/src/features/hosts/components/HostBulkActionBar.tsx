/**
 * Host Bulk Action Bar
 * Appears when hosts are selected - allows bulk tag operations
 */

import { useState, useRef, useEffect } from 'react'
import { X, Tag, Plus, Minus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { TagInput } from '@/components/TagInput'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'

interface HostBulkActionBarProps {
  selectedHostIds: Set<string>
  onClearSelection: () => void
  onTagsUpdated: () => void
}

export function HostBulkActionBar({
  selectedHostIds,
  onClearSelection,
  onTagsUpdated
}: HostBulkActionBarProps) {
  const [showTagInput, setShowTagInput] = useState(false)
  const [tagMode, setTagMode] = useState<'add' | 'remove'>('add')
  const [tags, setTags] = useState<string[]>([])
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([])
  const tagInputRef = useRef<HTMLDivElement>(null)

  const hostCount = selectedHostIds.size

  // Close tag input when clicking outside
  useEffect(() => {
    if (!showTagInput) return

    const handleClickOutside = (event: MouseEvent) => {
      if (tagInputRef.current && !tagInputRef.current.contains(event.target as Node)) {
        setShowTagInput(false)
        setTags([])
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showTagInput])

  // Fetch tag suggestions on mount
  useEffect(() => {
    const fetchSuggestions = async () => {
      try {
        const response = await apiClient.get<{ tags: string[] }>('/hosts/tags/suggest', {
          params: { q: '', limit: 50 }
        })
        setTagSuggestions(response.tags)
      } catch (error) {
        console.error('Failed to fetch tag suggestions:', error)
      }
    }
    fetchSuggestions()
  }, [])

  const handleAddTags = () => {
    setTagMode('add')
    setShowTagInput(true)
    setTags([])
  }

  const handleRemoveTags = () => {
    setTagMode('remove')
    setShowTagInput(true)
    setTags([])
  }

  const handleApplyTags = async () => {
    if (tags.length === 0) {
      toast.error('Please enter at least one tag')
      return
    }

    const hostIds = Array.from(selectedHostIds)
    let successCount = 0
    let errorCount = 0

    toast.loading(`${tagMode === 'add' ? 'Adding' : 'Removing'} tags for ${hostCount} host${hostCount > 1 ? 's' : ''}...`, {
      id: 'bulk-tags'
    })

    // Update tags for each host
    for (const hostId of hostIds) {
      try {
        await apiClient.patch(`/hosts/${hostId}/tags`, {
          tags_to_add: tagMode === 'add' ? tags : [],
          tags_to_remove: tagMode === 'remove' ? tags : []
        })
        successCount++
      } catch (error) {
        console.error(`Failed to update tags for host ${hostId}:`, error)
        errorCount++
      }
    }

    // Show result
    toast.dismiss('bulk-tags')
    if (errorCount === 0) {
      toast.success(`Successfully ${tagMode === 'add' ? 'added' : 'removed'} tags for ${successCount} host${successCount > 1 ? 's' : ''}`)
    } else if (successCount > 0) {
      toast.warning(`Updated ${successCount} host${successCount > 1 ? 's' : ''}, ${errorCount} failed`)
    } else {
      toast.error(`Failed to update tags for all hosts`)
    }

    // Reset and notify parent
    setShowTagInput(false)
    setTags([])
    onTagsUpdated()
  }

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
      <div className="bg-card border border-border rounded-lg shadow-lg p-4 min-w-[500px]">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className="flex items-center justify-center w-8 h-8 rounded-full bg-primary/10 text-primary">
              {hostCount}
            </div>
            <span className="text-sm font-medium">
              {hostCount} host{hostCount > 1 ? 's' : ''} selected
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClearSelection}
            className="h-8 w-8 p-0"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {!showTagInput ? (
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleAddTags}
              className="flex-1"
            >
              <Plus className="h-4 w-4 mr-2" />
              Add Tags
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleRemoveTags}
              className="flex-1"
            >
              <Minus className="h-4 w-4 mr-2" />
              Remove Tags
            </Button>
          </div>
        ) : (
          <div ref={tagInputRef} className="space-y-3">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Tag className="h-4 w-4" />
              <span>
                {tagMode === 'add' ? 'Add tags to' : 'Remove tags from'} {hostCount} host{hostCount > 1 ? 's' : ''}
              </span>
            </div>
            <TagInput
              value={tags}
              onChange={setTags}
              suggestions={tagSuggestions}
              placeholder={tagMode === 'add' ? 'Type tags (prod, dev, us-west-1...)' : 'Type tags to remove...'}
              maxTags={20}
            />
            <div className="flex gap-2">
              <Button
                variant="default"
                size="sm"
                onClick={handleApplyTags}
                disabled={tags.length === 0}
                className="flex-1"
              >
                {tagMode === 'add' ? 'Add' : 'Remove'} Tags
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setShowTagInput(false)
                  setTags([])
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
