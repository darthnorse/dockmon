/**
 * TagEditor - Inline tag management for containers
 *
 * Features:
 * - Display tags as chips (user first, then derived)
 * - User tags: removable with ×
 * - Derived tags: locked with 🔒 tooltip
 * - Inline editor with combobox and type-ahead
 * - Optimistic updates with toast notifications
 * - Keyboard shortcuts: Esc to cancel, Cmd/Ctrl+Enter to save
 * - Validation: 1-24 chars, trim, de-dupe
 */

import { useState, KeyboardEvent, useRef, useEffect } from 'react'
import { X, Tag, Edit, Lock } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import { validateTag, normalizeTag, isDerivedTag, validateTagSuggestionsResponse } from '@/lib/validation/tags'
import { TagChip } from '@/components/TagChip'
import type { Container } from '../../types'

interface TagEditorProps {
  tags: string[]
  containerId: string
  hostId: string
}

export function TagEditor({ tags, containerId, hostId }: TagEditorProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [inputValue, setInputValue] = useState('')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const suggestionsRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()

  const userTags = tags.filter(tag => !isDerivedTag(tag))
  const derivedTags = tags.filter(tag => isDerivedTag(tag))

  // Initialize selected tags when entering edit mode
  useEffect(() => {
    if (isEditing) {
      setSelectedTags(userTags)
      setError(null)
      inputRef.current?.focus()
    }
    // Only reset when isEditing changes, not when userTags changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing])

  // Fetch tag suggestions from API
  useEffect(() => {
    if (!showSuggestions) {
      setSuggestions([])
      return
    }

    let cancelled = false

    const fetchSuggestions = async () => {
      try {
        const data = await apiClient.get<{ tags: string[] }>(`/tags/suggest?q=${encodeURIComponent(inputValue)}`)
        if (!cancelled) {
          const validTags = validateTagSuggestionsResponse(data)
          if (validTags.length > 0) {
            setSuggestions(validTags)
          } else {
            debug.warn('TagEditor', 'Invalid tag suggestions response format:', data)
            setSuggestions([])
          }
        }
      } catch (error) {
        if (!cancelled) {
          debug.error('TagEditor', 'Failed to fetch tag suggestions:', error)
          setSuggestions([])
        }
      }
    }

    const debounce = setTimeout(fetchSuggestions, 200)
    return () => {
      cancelled = true
      clearTimeout(debounce)
    }
  }, [inputValue, showSuggestions])

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (suggestionsRef.current && !suggestionsRef.current.contains(e.target as Node) &&
          inputRef.current && !inputRef.current.contains(e.target as Node)) {
        setShowSuggestions(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const addTag = (tag: string) => {
    const validation = validateTag(tag, selectedTags)
    if (!validation.valid) {
      setError(validation.error || 'Invalid tag')
      return
    }

    const normalizedTag = normalizeTag(tag)
    setSelectedTags([...selectedTags, normalizedTag])
    setInputValue('')
    setError(null)
    setShowSuggestions(false)
  }

  const removeTag = (tagToRemove: string) => {
    setSelectedTags(selectedTags.filter(t => t !== tagToRemove))
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (inputValue.trim()) {
        addTag(inputValue.trim())
      }
    } else if (e.key === 'Backspace' && inputValue === '' && selectedTags.length > 0) {
      // Remove last tag on backspace when input is empty
      const lastTag = selectedTags[selectedTags.length - 1]
      if (lastTag) {
        removeTag(lastTag)
      }
    }
  }

  const handleCancel = () => {
    setIsEditing(false)
    setInputValue('')
    setError(null)
    setShowSuggestions(false)
  }

  const handleSave = async () => {
    // Determine what changed
    const currentUserTags = new Set(userTags)
    const newUserTags = new Set(selectedTags)

    const tagsToAdd = Array.from(newUserTags).filter(tag => !currentUserTags.has(tag))
    const tagsToRemove = Array.from(currentUserTags).filter(tag => !newUserTags.has(tag))

    if (tagsToAdd.length === 0 && tagsToRemove.length === 0) {
      // No changes
      handleCancel()
      return
    }

    // Optimistic update
    const optimisticTags = [...selectedTags, ...derivedTags]
    queryClient.setQueryData<Container[]>(['containers'], (old) => {
      if (!old) return old
      return old.map((c) =>
        c.id === containerId ? { ...c, tags: optimisticTags } : c
      )
    })

    try {
      await apiClient.patch(`/hosts/${hostId}/containers/${containerId}/tags`, {
        tags_to_add: tagsToAdd,
        tags_to_remove: tagsToRemove,
      })

      // Success toast
      const addedCount = tagsToAdd.length
      const removedCount = tagsToRemove.length
      let message = ''
      if (addedCount > 0 && removedCount > 0) {
        message = `Added ${addedCount} and removed ${removedCount} tag${removedCount > 1 ? 's' : ''}`
      } else if (addedCount > 0) {
        message = `Added ${addedCount} tag${addedCount > 1 ? 's' : ''}`
      } else {
        message = `Removed ${removedCount} tag${removedCount > 1 ? 's' : ''}`
      }

      toast.success(message)

      // Refetch to get server state
      queryClient.invalidateQueries({ queryKey: ['containers'] })

      handleCancel()
    } catch (err) {
      // Revert optimistic update
      queryClient.invalidateQueries({ queryKey: ['containers'] })

      const errorMessage = err instanceof Error ? err.message : 'Failed to update tags'
      toast.error(errorMessage)
      setError(errorMessage)
    }
  }

  // Quick remove for individual user tags (not in edit mode)
  const handleQuickRemove = async (tagToRemove: string) => {
    // Optimistic update
    const optimisticTags = tags.filter(t => t !== tagToRemove)
    queryClient.setQueryData<Container[]>(['containers'], (old) => {
      if (!old) return old
      return old.map((c) =>
        c.id === containerId ? { ...c, tags: optimisticTags } : c
      )
    })

    try {
      await apiClient.patch(`/hosts/${hostId}/containers/${containerId}/tags`, {
        tags_to_add: [],
        tags_to_remove: [tagToRemove],
      })

      toast.success(`Removed tag "${tagToRemove}"`)
      queryClient.invalidateQueries({ queryKey: ['containers'] })
    } catch (err) {
      queryClient.invalidateQueries({ queryKey: ['containers'] })
      toast.error('Failed to remove tag')
    }
  }

  if (isEditing) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Tag className="w-4 h-4 text-muted-foreground" />
            <h4 className="text-sm font-medium text-foreground">Tags</h4>
          </div>
        </div>

        {/* Inline Editor */}
        <div className="space-y-2">
          {/* Selected tags as chips */}
          <div className="flex flex-wrap gap-1.5 min-h-[32px] items-center">
            {selectedTags.map((tag) => (
              <div
                key={tag}
                className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-primary/10 text-primary"
              >
                <span>{tag}</span>
                <button
                  onClick={() => removeTag(tag)}
                  className="hover:bg-black/10 dark:hover:bg-white/10 rounded p-0.5"
                  aria-label={`Remove ${tag}`}
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}

            {/* Input */}
            <div className="relative flex-1 min-w-[120px]">
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => {
                  setInputValue(e.target.value)
                  setError(null)
                }}
                onKeyDown={handleKeyDown}
                onFocus={() => setShowSuggestions(true)}
                placeholder="Type to add..."
                className="w-full px-2 py-1 text-sm border border-border rounded bg-background focus:outline-none focus:ring-2 focus:ring-primary"
                aria-label="Add new tag"
                aria-describedby={error ? "tag-error" : "tag-helper"}
                aria-invalid={error ? "true" : "false"}
                aria-autocomplete="list"
                aria-controls={showSuggestions && suggestions.length > 0 ? "tag-suggestions" : undefined}
                aria-expanded={showSuggestions && suggestions.length > 0}
              />

              {/* Suggestions dropdown */}
              {showSuggestions && suggestions.length > 0 && (
                <div
                  ref={suggestionsRef}
                  id="tag-suggestions"
                  role="listbox"
                  className="absolute top-full left-0 mt-1 w-full bg-popover border border-border rounded-md shadow-md max-h-60 overflow-y-auto z-50 p-1"
                >
                  {suggestions.map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => addTag(suggestion)}
                      className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-left hover:bg-accent hover:text-accent-foreground transition-colors"
                      role="option"
                      aria-selected="false"
                    >
                      <TagChip tag={suggestion} size="sm" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Helper text or error */}
          {error ? (
            <p id="tag-error" className="text-xs text-danger" role="alert">{error}</p>
          ) : (
            <p id="tag-helper" className="text-xs text-muted-foreground">
              Enter to add · Backspace to remove last
            </p>
          )}

          {/* Save/Cancel buttons */}
          <div className="flex gap-2">
            <button
              onClick={handleSave}
              className="px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded hover:bg-primary/90 transition-colors"
              aria-label="Save tag changes"
            >
              Save
            </button>
            <button
              onClick={handleCancel}
              className="px-3 py-1.5 text-sm border border-border rounded hover:bg-muted transition-colors"
              aria-label="Cancel tag editing"
            >
              Cancel
            </button>
          </div>
        </div>

        {/* Derived tags (read-only in editor) */}
        {derivedTags.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <h4 className="text-xs font-medium text-muted-foreground">Derived (locked)</h4>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {derivedTags.map((tag) => (
                <div
                  key={tag}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs border border-border bg-transparent text-muted-foreground cursor-help"
                  title="Derived from docker-compose"
                >
                  <Lock className="w-3 h-3" />
                  <span>{tag}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  // View mode
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Tag className="w-4 h-4 text-muted-foreground" />
          <h4 className="text-sm font-medium text-foreground">Tags</h4>
        </div>
        <button
          onClick={() => setIsEditing(true)}
          className="text-xs text-primary hover:text-primary/80 transition-colors flex items-center gap-1"
          title="Edit tags"
          aria-label="Edit container tags"
        >
          <Edit className="w-3 h-3" />
          Edit
        </button>
      </div>

      {/* User Tags */}
      {userTags.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {userTags.map((tag) => (
            <div
              key={tag}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-primary/10 text-primary group"
            >
              <span>{tag}</span>
              <button
                onClick={() => handleQuickRemove(tag)}
                className="opacity-60 hover:opacity-100 hover:bg-black/10 dark:hover:bg-white/10 rounded p-0.5 transition-all"
                aria-label={`Remove ${tag}`}
                title="Remove tag"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <button
          onClick={() => setIsEditing(true)}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          No tags · Click to add
        </button>
      )}

      {/* Derived Tags */}
      {derivedTags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {derivedTags.map((tag) => (
            <div
              key={tag}
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs border border-border bg-transparent text-muted-foreground cursor-help"
              title="Derived from docker-compose (locked)"
            >
              <Lock className="w-3 h-3" />
              <span>{tag}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
