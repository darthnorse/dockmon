/**
 * useContainerTagEditor - Custom hook for container tag editing logic
 *
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
 * } = useContainerTagEditor({ hostId, containerId, currentTags })
 */

import { useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'

interface UseContainerTagEditorOptions {
  hostId: string
  containerId: string
  currentTags: string[]
}

interface UseContainerTagEditorReturn {
  isEditing: boolean
  editedTags: string[]
  tagSuggestions: string[]
  isLoading: boolean
  setEditedTags: (tags: string[]) => void
  handleStartEdit: () => void
  handleCancelEdit: () => void
  handleSaveTags: () => Promise<void>
}

export function useContainerTagEditor({
  hostId,
  containerId,
  currentTags,
}: UseContainerTagEditorOptions): UseContainerTagEditorReturn {
  const queryClient = useQueryClient()
  const [isEditing, setIsEditing] = useState(false)
  const [editedTags, setEditedTags] = useState<string[]>([])
  const [tagSuggestions, setTagSuggestions] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(false)

  // Fetch tag suggestions on mount
  useEffect(() => {
    const fetchSuggestions = async () => {
      try {
        const response = await apiClient.get<{ tags: Array<{name: string} | string> }>('/tags/suggest', {
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
      // Calculate tags to add and remove
      const tagsToAdd = editedTags.filter(tag => !currentTags.includes(tag))
      const tagsToRemove = currentTags.filter(tag => !editedTags.includes(tag))

      if (tagsToAdd.length === 0 && tagsToRemove.length === 0) {
        toast.info('No changes to save')
        setIsEditing(false)
        return
      }

      await apiClient.patch(`/hosts/${hostId}/containers/${containerId}/tags`, {
        tags_to_add: tagsToAdd,
        tags_to_remove: tagsToRemove
      })

      toast.success('Container tags updated successfully')
      setIsEditing(false)

      // Refetch containers to get updated tags
      queryClient.invalidateQueries({ queryKey: ['containers'] })
    } catch (error) {
      console.error('Failed to update container tags:', error)
      toast.error('Failed to update container tags')
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
