/**
 * Bulk Action Bar Component
 *
 * Sticky bottom bar that appears when containers are selected
 * Features three collapsible sections side by side:
 * - Run Actions: Start, Stop, Restart
 * - Manage State: Auto-Restart (Enable/Disable), Desired State (Should Run/On-Demand)
 * - Tags: Add/Remove tags
 */

import { useState, useRef, useEffect } from 'react'
import { X, Tag, ChevronDown, ChevronUp, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { Container } from '../types'

interface BulkActionBarProps {
  selectedCount: number
  selectedContainers: Container[]
  onClearSelection: () => void
  onAction: (action: 'start' | 'stop' | 'restart') => void
  onTagUpdate: (mode: 'add' | 'remove', tags: string[]) => Promise<void>
  onAutoRestartUpdate?: (enabled: boolean) => Promise<void>
  onDesiredStateUpdate?: (state: 'should_run' | 'on_demand') => Promise<void>
}

type TagMode = 'add' | 'remove'
type AutoRestartMode = 'enable' | 'disable'
type DesiredStateMode = 'should_run' | 'on_demand'

export function BulkActionBar({
  selectedCount,
  selectedContainers,
  onClearSelection,
  onAction,
  onTagUpdate,
  onAutoRestartUpdate,
  onDesiredStateUpdate
}: BulkActionBarProps) {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['run-actions', 'manage-state', 'tags']))

  // Tag state
  const [tagMode, setTagMode] = useState<TagMode>('add')
  const [inputValue, setInputValue] = useState('')
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)

  // Auto-Restart state
  const [autoRestartMode, setAutoRestartMode] = useState<AutoRestartMode>('enable')

  // Desired State state
  const [desiredStateMode, setDesiredStateMode] = useState<DesiredStateMode>('should_run')

  const [isLoading, setIsLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const suggestionsRef = useRef<HTMLDivElement>(null)

  const toggleSection = (section: string) => {
    const newExpanded = new Set(expandedSections)
    if (newExpanded.has(section)) {
      newExpanded.delete(section)
    } else {
      newExpanded.add(section)
    }
    setExpandedSections(newExpanded)
  }

  // Get tag suggestions based on mode
  const getTagSuggestions = () => {
    if (tagMode === 'remove') {
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

    return { intersection: [], union: [] }
  }

  // Fetch suggestions from API (for add mode)
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
      const lastTag = selectedTags[selectedTags.length - 1]
      if (lastTag) {
        removeTag(lastTag)
      }
    } else if (e.key === 'Escape') {
      setShowSuggestions(false)
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

  const handleApplyTags = async () => {
    if (selectedTags.length === 0) return

    setIsLoading(true)
    try {
      await onTagUpdate(tagMode, selectedTags)
      setSelectedTags([])
      setInputValue('')
    } catch (error) {
      console.error('Failed to update tags:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleApplyAutoRestart = async () => {
    if (!onAutoRestartUpdate) return

    setIsLoading(true)
    try {
      await onAutoRestartUpdate(autoRestartMode === 'enable')
    } catch (error) {
      console.error('Failed to update auto-restart:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleApplyDesiredState = async () => {
    if (!onDesiredStateUpdate) return

    setIsLoading(true)
    try {
      await onDesiredStateUpdate(desiredStateMode)
    } catch (error) {
      console.error('Failed to update desired state:', error)
    } finally {
      setIsLoading(false)
    }
  }

  if (selectedCount === 0) {
    return null
  }

  const tagSuggestions = tagMode === 'remove' ? getTagSuggestions() : { intersection: [], union: [] }

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 border-t border-border bg-surface-1 shadow-lg">
      <div className="container mx-auto px-6 py-3">
        <div className="flex items-center justify-between gap-4">
          {/* Left: Selection count */}
          <div className="flex items-center gap-2">
            <div className="flex items-center justify-center h-6 w-6 rounded-full bg-primary text-primary-foreground text-xs font-medium">
              ✓
            </div>
            <span className="text-sm font-medium text-foreground">
              {selectedCount} container{selectedCount !== 1 ? 's' : ''} selected
            </span>
          </div>

          {/* Right: Action sections and close button */}
          <div className="flex items-start gap-3">
            {/* Run Actions */}
            <div className="border border-border rounded-lg bg-background">
              <button
                onClick={() => toggleSection('run-actions')}
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-muted transition-colors rounded-t-lg w-full"
              >
                <span>Run Actions</span>
                {expandedSections.has('run-actions') ? (
                  <ChevronUp className="h-3.5 w-3.5" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5" />
                )}
              </button>

              {expandedSections.has('run-actions') && (
                <div className="p-3 border-t border-border flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onAction('start')}
                    disabled={isLoading}
                    className="text-success hover:text-success hover:bg-success/10"
                  >
                    Start
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onAction('stop')}
                    disabled={isLoading}
                    className="text-danger hover:text-danger hover:bg-danger/10"
                  >
                    Stop
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onAction('restart')}
                    disabled={isLoading}
                    className="text-info hover:text-info hover:bg-info/10"
                  >
                    Restart
                  </Button>
                </div>
              )}
            </div>

            {/* Manage State */}
            <div className="border border-border rounded-lg bg-background">
              <button
                onClick={() => toggleSection('manage-state')}
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-muted transition-colors rounded-t-lg w-full"
              >
                <span>Manage State</span>
                {expandedSections.has('manage-state') ? (
                  <ChevronUp className="h-3.5 w-3.5" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5" />
                )}
              </button>

              {expandedSections.has('manage-state') && (
                <div className="p-3 border-t border-border space-y-3 min-w-[400px]">
                  {/* Auto-Restart */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Set Auto-Restart</span>
                      <div className="group relative">
                        <Info className="h-3 w-3 text-muted-foreground cursor-help" />
                        <div className="invisible group-hover:visible absolute left-0 bottom-full mb-2 z-10 w-64 p-2 text-xs bg-surface-1 border border-border rounded shadow-lg">
                          DockMon will automatically restart these containers if they stop unexpectedly
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="radio"
                          name="autoRestart"
                          checked={autoRestartMode === 'enable'}
                          onChange={() => setAutoRestartMode('enable')}
                          className="h-3.5 w-3.5"
                          disabled={isLoading}
                        />
                        <span className="text-sm">Enable</span>
                      </label>
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="radio"
                          name="autoRestart"
                          checked={autoRestartMode === 'disable'}
                          onChange={() => setAutoRestartMode('disable')}
                          className="h-3.5 w-3.5"
                          disabled={isLoading}
                        />
                        <span className="text-sm">Disable</span>
                      </label>
                      <Button
                        variant="default"
                        size="sm"
                        onClick={handleApplyAutoRestart}
                        disabled={isLoading || !onAutoRestartUpdate}
                        className="ml-auto"
                      >
                        {isLoading ? 'Applying...' : 'Apply'}
                      </Button>
                    </div>
                  </div>

                  {/* Desired State */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-medium text-muted-foreground">Desired State</span>
                      <div className="group relative">
                        <Info className="h-3 w-3 text-muted-foreground cursor-help" />
                        <div className="invisible group-hover:visible absolute left-0 bottom-full mb-2 z-10 w-64 p-2 text-xs bg-surface-1 border border-border rounded shadow-lg">
                          Should Run: Stopped state is treated as a warning. On-Demand: Stopped state is informational only
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="radio"
                          name="desiredState"
                          checked={desiredStateMode === 'should_run'}
                          onChange={() => setDesiredStateMode('should_run')}
                          className="h-3.5 w-3.5"
                          disabled={isLoading}
                        />
                        <span className="text-sm">Should Run</span>
                      </label>
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="radio"
                          name="desiredState"
                          checked={desiredStateMode === 'on_demand'}
                          onChange={() => setDesiredStateMode('on_demand')}
                          className="h-3.5 w-3.5"
                          disabled={isLoading}
                        />
                        <span className="text-sm">On-Demand</span>
                      </label>
                      <Button
                        variant="default"
                        size="sm"
                        onClick={handleApplyDesiredState}
                        disabled={isLoading || !onDesiredStateUpdate}
                        className="ml-auto"
                      >
                        {isLoading ? 'Applying...' : 'Apply'}
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Tags */}
            <div className="border border-border rounded-lg bg-background">
              <button
                onClick={() => toggleSection('tags')}
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-muted transition-colors rounded-t-lg w-full"
              >
                <span>Tags</span>
                {expandedSections.has('tags') ? (
                  <ChevronUp className="h-3.5 w-3.5" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5" />
                )}
              </button>

              {expandedSections.has('tags') && (
                <div className="p-3 border-t border-border space-y-3 min-w-[500px]">
                  {/* Tag mode selector */}
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-medium text-muted-foreground">Action:</span>
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name="tagMode"
                        checked={tagMode === 'add'}
                        onChange={() => {
                          setTagMode('add')
                          setSelectedTags([])
                        }}
                        className="h-3.5 w-3.5"
                        disabled={isLoading}
                      />
                      <span className="text-sm">Add</span>
                    </label>
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name="tagMode"
                        checked={tagMode === 'remove'}
                        onChange={() => {
                          setTagMode('remove')
                          setSelectedTags([])
                        }}
                        className="h-3.5 w-3.5"
                        disabled={isLoading}
                      />
                      <span className="text-sm">Remove</span>
                    </label>
                  </div>

                  {/* Tag input */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 relative">
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
                        placeholder={selectedTags.length === 0 ? "Type to add tags..." : ""}
                        disabled={isLoading}
                        className="flex-1 px-2 py-1 text-sm border border-border rounded bg-background focus:outline-none focus:ring-2 focus:ring-primary min-w-[150px]"
                      />

                      <Button
                        variant="default"
                        size="sm"
                        onClick={handleApplyTags}
                        disabled={selectedTags.length === 0 || isLoading}
                      >
                        {isLoading ? 'Applying...' : 'Apply'}
                      </Button>

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
                </div>
              )}
            </div>

            {/* Clear selection button */}
            <Button
              variant="ghost"
              size="icon"
              onClick={onClearSelection}
              title="Clear selection"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
