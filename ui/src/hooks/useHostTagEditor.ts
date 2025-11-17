/**
 * useHostTagEditor - Custom hook for host tag editing logic
 *
 * Eliminates code duplication between HostOverviewTab and HostTagsSection
 * Provides all state and handlers needed for tag editing with optimistic updates
 *
 * FEATURES:
 * - Manages edit mode state
 * - Fetches tag suggestions from API
 * - Handles save/cancel operations
 * - Calculates tag diffs (add/remove)
 * - Optimistic updates with invalidation
 * - Toast notifications
 *
 * USAGE:
 * const {
 *   isEditing,
 *   editedTags,
 *   tagSuggestions,
 *   isLoading,
 *   setEditedTags,
 *   handleStartEdit,
 *   handleCancelEdit,
 *   handleSaveTags
 * } = useHostTagEditor({ hostId, currentTags })
 */

import { useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'

interface UseHostTagEditorOptions {
  hostId: string
  currentTags: string[]
}

interface UseHostTagEditorReturn {
  isEditing: boolean
  editedTags: string[]
  tagSuggestions: string[]
  isLoading: boolean
  setEditedTags: (tags: string[]) => void
  handleStartEdit: () => void
  handleCancelEdit: () => void
  handleSaveTags: () => Promise<void>
}

export function useHostTagEditor({
  hostId,
  currentTags,
}: UseHostTagEditorOptions): UseHostTagEditorReturn {
  const queryClient = useQueryClient()
  const [isEditing, setIsEditing] = useState(false)
  const [editedTags, setEditedTags] = useState<string[]>([])
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(false)

  // Fetch tag suggestions on mount
  useEffect(() => {
    const fetchSuggestions = async () => {
      try {
        const response = await apiClient.get<{ tags: Array<{name: string} | string> }>('/hosts/tags/suggest', {
          params: { q: '', limit: 50 }
        })
        // Tags API returns objects like {id, name, color, kind}, extract just the names
        const tagNames = response.tags.map(t => typeof t === 'string' ? t : t.name)
        setTagSuggestions(tagNames)
      } catch (error) {
        console.error('Failed to fetch tag suggestions:', error)
      }
    }
    fetchSuggestions()
  }, [])

  const handleStartEdit = () => {
    setEditedTags([...currentTags])
    setIsEditing(true)
  }

  const handleCancelEdit = () => {
    setIsEditing(false)
    setEditedTags([])
  }

  const handleSaveTags = async () => {
    setIsLoading(true)

    try {
      // Check if tags changed at all
      const tagsChanged = JSON.stringify(editedTags) !== JSON.stringify(currentTags)

      if (!tagsChanged) {
        toast.info('No changes to save')
        setIsEditing(false)
        return
      }

      // Check if order changed (tags are same but in different order)
      const sameTagsDifferentOrder =
        editedTags.length === currentTags.length &&
        editedTags.every(tag => currentTags.includes(tag)) &&
        JSON.stringify(editedTags) !== JSON.stringify(currentTags)

      // Use ordered mode if reordering, delta mode if adding/removing
      if (sameTagsDifferentOrder) {
        // Reorder mode: send complete ordered list (v2.1.8-hotfix.1+)
        await apiClient.patch(`/hosts/${hostId}/tags`, {
          ordered_tags: editedTags
        })
      } else {
        // Delta mode: calculate add/remove (backwards compatible)
        const tagsToAdd = editedTags.filter(tag => !currentTags.includes(tag))
        const tagsToRemove = currentTags.filter(tag => !editedTags.includes(tag))

        await apiClient.patch(`/hosts/${hostId}/tags`, {
          tags_to_add: tagsToAdd,
          tags_to_remove: tagsToRemove
        })
      }

      toast.success('Host tags updated successfully')
      setIsEditing(false)

      // Refetch hosts to get updated tags
      queryClient.invalidateQueries({ queryKey: ['hosts'] })
    } catch (error) {
      console.error('Failed to update host tags:', error)
      toast.error('Failed to update host tags')
    } finally {
      setIsLoading(false)
    }
  }

  return {
    isEditing,
    editedTags,
    tagSuggestions,
    isLoading,
    setEditedTags,
    handleStartEdit,
    handleCancelEdit,
    handleSaveTags,
  }
}
