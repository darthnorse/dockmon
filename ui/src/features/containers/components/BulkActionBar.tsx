/**
 * Bulk Action Bar Component
 *
 * Sticky bottom bar that appears when containers are selected
 * Features:
 * - Basic container actions (Start, Stop, Restart)
 * - Expandable tag management editor with Add/Remove/Replace modes
 * - Tag suggestions from API
 * - Inline confirmation for destructive Replace mode
 */

import { useState, useRef, useEffect } from 'react'
import { X, Tag } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { Container } from '../types'

interface BulkActionBarProps {
  selectedCount: number
  selectedContainers: Container[]
  onClearSelection: () => void
  onAction: (action: 'start' | 'stop' | 'restart') => void
  onTagUpdate: (mode: 'add' | 'remove', tags: string[]) => Promise<void>
}

type TagMode = 'add' | 'remove'

export function BulkActionBar({
  selectedCount,
  selectedContainers,
  onClearSelection,
  onAction,
  onTagUpdate
}: BulkActionBarProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const [tagMode, setTagMode] = useState<TagMode>('add')
  const [inputValue, setInputValue] = useState('')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const suggestionsRef = useRef<HTMLDivElement>(null)

  // Get tag suggestions based on mode
  const getTagSuggestions = () => {
    if (tagMode === 'remove') {
      // For remove mode, show intersection (tags on ALL selected) and union (tags on SOME)
      const tagCounts = new Map<string, number>()

      selectedContainers.forEach(container => {
        container.tags?.forEach(tag => {
          tagCounts.set(tag, (tagCounts.get(tag) || 0) + 1)
        })
      })

      const intersection: string[] = []
      const union: string[] = []

      tagCounts.forEach((count, tag) => {
        if (!tag.startsWith('compose:') && !tag.startsWith('swarm:')) {
          if (count === selectedContainers.length) {
            intersection.push(tag)
          } else {
            union.push(tag)
          }
        }
      })

      return { intersection, union }
    }

    // For add/replace modes, just return recently used tags (we'll fetch from API)
    return { intersection: [], union: [] }
  }

  // Fetch suggestions from API (for add/replace modes)
  useEffect(() => {
    if (!showSuggestions || tagMode === 'remove') return

    const fetchSuggestions = async () => {
      try {
        const response = await fetch(`/api/tags/suggest?q=${encodeURIComponent(inputValue)}`)
        if (response.ok) {
          const data = await response.json()
          setSuggestions(data.tags || [])
        }
      } catch (error) {
        console.error('Failed to fetch tag suggestions:', error)
      }
    }

    const debounce = setTimeout(fetchSuggestions, 200)
    return () => clearTimeout(debounce)
  }, [inputValue, showSuggestions, tagMode])

  // Handle clicking outside suggestions
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

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && inputValue.trim()) {
      e.preventDefault()
      addTag(inputValue.trim())
    } else if (e.key === 'Backspace' && inputValue === '' && selectedTags.length > 0) {
      // Remove last tag on backspace when input is empty
      const lastTag = selectedTags[selectedTags.length - 1]
      if (lastTag) {
        removeTag(lastTag)
      }
    } else if (e.key === 'Escape') {
      handleCancel()
    }
  }

  const addTag = (tag: string) => {
    const normalizedTag = tag.toLowerCase()
    if (!selectedTags.includes(normalizedTag)) {
      setSelectedTags([...selectedTags, normalizedTag])
      setInputValue('')
      setShowSuggestions(false)
    }
  }

  const removeTag = (tag: string) => {
    setSelectedTags(selectedTags.filter(t => t !== tag))
  }

  const handleApply = async () => {
    if (selectedTags.length === 0) return

    setIsLoading(true)
    try {
      await onTagUpdate(tagMode, selectedTags)
      // Reset state on success
      setIsExpanded(false)
      setSelectedTags([])
      setInputValue('')
    } catch (error) {
      console.error('Failed to update tags:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleCancel = () => {
    setIsExpanded(false)
    setSelectedTags([])
    setInputValue('')
    setShowSuggestions(false)
  }

  const handleModeChange = (mode: TagMode) => {
    setTagMode(mode)
    setSelectedTags([])
  }

  if (selectedCount === 0) {
    return null
  }

  const tagSuggestions = tagMode === 'remove' ? getTagSuggestions() : { intersection: [], union: [] }

  return (
    <div
      className={`fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-surface-1 shadow-lg transition-all duration-200 ${
        isExpanded ? 'h-[120px]' : 'h-[48px]'
      }`}
    >
      <div className="container mx-auto px-6 h-full">
        {!isExpanded ? (
          // Collapsed state
          <div className="flex items-center justify-between h-full">
            {/* Left: Selection count */}
            <div className="flex items-center gap-2">
              <div className="flex items-center justify-center h-6 w-6 rounded-full bg-primary text-primary-foreground text-xs font-medium">
                ✓
              </div>
              <span className="text-sm font-medium text-foreground">
                {selectedCount} container{selectedCount !== 1 ? 's' : ''} selected
              </span>
            </div>

            {/* Right: Actions */}
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => onAction('start')}
                className="text-success hover:text-success hover:bg-success/10"
              >
                Start
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onAction('stop')}
                className="text-danger hover:text-danger hover:bg-danger/10"
              >
                Stop
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onAction('restart')}
                className="text-info hover:text-info hover:bg-info/10"
              >
                Restart
              </Button>

              {/* Manage Tags - Primary Action */}
              <div className="h-6 w-px bg-border mx-2" />
              <Button
                variant="default"
                size="sm"
                onClick={() => setIsExpanded(true)}
                className="bg-primary text-primary-foreground"
              >
                <Tag className="h-3.5 w-3.5 mr-1.5" />
                Manage Tags
              </Button>

              {/* Clear selection */}
              <Button
                variant="ghost"
                size="icon"
                onClick={onClearSelection}
                className="ml-4"
                title="Clear selection"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ) : (
          // Expanded state - Tag editor
          <div className="flex flex-col h-full py-3 gap-3">
            {/* Header row */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                {/* Selection count */}
                <span className="text-sm font-medium text-foreground">
                  {selectedCount} container{selectedCount !== 1 ? 's' : ''} selected
                </span>

                {/* Mode selector */}
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Mode:</span>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="radio"
                      name="tagMode"
                      checked={tagMode === 'add'}
                      onChange={() => handleModeChange('add')}
                      className="h-3.5 w-3.5"
                    />
                    <span className="text-sm">Add</span>
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="radio"
                      name="tagMode"
                      checked={tagMode === 'remove'}
                      onChange={() => handleModeChange('remove')}
                      className="h-3.5 w-3.5"
                    />
                    <span className="text-sm">Remove</span>
                  </label>
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCancel}
                  disabled={isLoading}
                >
                  Cancel
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  onClick={handleApply}
                  disabled={selectedTags.length === 0 || isLoading}
                >
                  {isLoading ? 'Applying...' : 'Apply'}
                </Button>
              </div>
            </div>

            {/* Combobox row */}
            <div className="flex items-center gap-2 flex-1 relative">
              <Tag className="h-4 w-4 text-muted-foreground shrink-0" />

              {/* Selected tags as chips */}
              <div className="flex flex-wrap gap-1.5">
                {selectedTags.map(tag => (
                  <div
                    key={tag}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs bg-primary/10 text-primary"
                  >
                    <span>{tag}</span>
                    <button
                      onClick={() => removeTag(tag)}
                      className="hover:bg-black/10 dark:hover:bg-white/10 rounded p-0.5"
                      disabled={isLoading}
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>

              {/* Input */}
              <input
                ref={inputRef}
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                onFocus={() => setShowSuggestions(true)}
                placeholder={selectedTags.length === 0 ? "Type to add or pick tags..." : ""}
                disabled={isLoading}
                className="flex-1 px-2 py-1 text-sm border border-border rounded bg-background focus:outline-none focus:ring-2 focus:ring-primary min-w-[200px]"
              />

              {/* Suggestions dropdown */}
              {showSuggestions && (
                <div
                  ref={suggestionsRef}
                  className="absolute bottom-full left-8 mb-2 w-[300px] bg-surface-1 border border-border rounded-lg shadow-xl max-h-[200px] overflow-y-auto z-10"
                >
                  {tagMode === 'remove' ? (
                    <>
                      {tagSuggestions.intersection.length > 0 && (
                        <div className="p-2">
                          <div className="text-xs text-muted-foreground px-2 py-1">On all selected:</div>
                          {tagSuggestions.intersection.map(tag => (
                            <button
                              key={tag}
                              onClick={() => addTag(tag)}
                              className="w-full text-left px-3 py-2 text-sm hover:bg-muted rounded transition-colors"
                            >
                              {tag}
                            </button>
                          ))}
                        </div>
                      )}
                      {tagSuggestions.union.length > 0 && (
                        <div className="p-2 border-t border-border">
                          <div className="text-xs text-muted-foreground px-2 py-1">On some selected:</div>
                          {tagSuggestions.union.map(tag => (
                            <button
                              key={tag}
                              onClick={() => addTag(tag)}
                              className="w-full text-left px-3 py-2 text-sm hover:bg-muted rounded transition-colors flex items-center justify-between"
                            >
                              <span>{tag}</span>
                              <span className="text-xs text-muted-foreground">some</span>
                            </button>
                          ))}
                        </div>
                      )}
                      {tagSuggestions.intersection.length === 0 && tagSuggestions.union.length === 0 && (
                        <div className="p-4 text-sm text-muted-foreground text-center">
                          No tags to remove
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      {suggestions.length > 0 ? (
                        <div className="p-2">
                          {suggestions.map(tag => (
                            <button
                              key={tag}
                              onClick={() => addTag(tag)}
                              className="w-full text-left px-3 py-2 text-sm hover:bg-muted rounded transition-colors"
                            >
                              {tag}
                            </button>
                          ))}
                        </div>
                      ) : inputValue.trim() ? (
                        <div className="p-3 text-sm text-muted-foreground">
                          Press Enter to create "{inputValue.trim()}"
                        </div>
                      ) : (
                        <div className="p-3 text-sm text-muted-foreground">
                          Type to search or create tags
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
