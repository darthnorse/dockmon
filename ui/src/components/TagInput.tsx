/**
 * TagInput - Multi-select tag input with autocomplete and drag-to-reorder
 * Phase 3d Sub-Phase 5
 *
 * FEATURES:
 * - Multi-select chip input for tags
 * - Autocomplete from existing tags
 * - Drag-to-reorder tags (first tag = primary tag for grouping)
 * - Keyboard navigation (Enter to add, Backspace to delete last)
 * - Max 50 tags per host (enforced in Pydantic)
 * - Tag validation (lowercase, alphanumeric + hyphens/underscores)
 * - Visual indicator for primary tag
 *
 * USAGE:
 * <TagInput
 *   value={tags}
 *   onChange={setTags}
 *   suggestions={allTags}
 *   placeholder="Add tags..."
 *   showPrimaryIndicator={true}  // Show "Primary" badge on first tag
 * />
 */

import { useState, useRef, useEffect } from 'react'
import { X, GripVertical, Star } from 'lucide-react'
import { TagChip } from '@/components/TagChip'

export interface TagInputProps {
  value: string[]
  onChange: (tags: string[]) => void
  suggestions?: string[]
  placeholder?: string
  maxTags?: number
  disabled?: boolean
  error?: string
  showPrimaryIndicator?: boolean  // Show visual indicator for primary (first) tag
  mode?: 'add' | 'remove'  // Add or remove mode - affects suggestion filtering
}

export function TagInput({
  value,
  onChange,
  suggestions = [],
  placeholder = 'Add tags...',
  maxTags = 50,
  disabled = false,
  error,
  showPrimaryIndicator = false,
  mode = 'add',
}: TagInputProps) {
  const [inputValue, setInputValue] = useState('')
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [selectedSuggestionIndex, setSelectedSuggestionIndex] = useState(-1)
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Filter suggestions based on input
  // In 'add' mode: exclude already selected tags
  // In 'remove' mode: show all tags (user wants to see existing tags to remove them)
  const filteredSuggestions = suggestions
    .filter((tag) => mode === 'add' ? !value.includes(tag) : true)
    .filter((tag) => tag.toLowerCase().includes(inputValue.toLowerCase()))
    .slice(0, 10) // Max 10 suggestions

  // Normalize tag: lowercase, trim, replace spaces with hyphens
  const normalizeTag = (tag: string): string => {
    return tag
      .toLowerCase()
      .trim()
      .replace(/\s+/g, '-')
      .replace(/[^a-z0-9-_:]/g, '') // Allow colons for compose:project format
  }

  // Validate tag format
  const isValidTag = (tag: string): boolean => {
    if (!tag || tag.length === 0) return false
    if (tag.length > 50) return false // Max length per tag
    return /^[a-z0-9][a-z0-9-_:]*$/.test(tag)
  }

  // Add tag
  const addTag = (tag: string) => {
    const normalized = normalizeTag(tag)
    if (!normalized) return

    if (!isValidTag(normalized)) {
      // Invalid tag format
      return
    }

    if (value.includes(normalized)) {
      // Tag already exists
      return
    }

    if (value.length >= maxTags) {
      // Max tags reached
      return
    }

    onChange([...value, normalized])
    setInputValue('')
    setShowSuggestions(false)
    setSelectedSuggestionIndex(-1)
  }

  // Remove tag
  const removeTag = (tagToRemove: string) => {
    onChange(value.filter((tag) => tag !== tagToRemove))
  }

  // Drag and drop handlers for reordering tags
  const handleDragStart = (e: React.DragEvent, index: number) => {
    setDraggedIndex(index)
    e.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault()
    if (draggedIndex === null || draggedIndex === index) return
    setDragOverIndex(index)
  }

  const handleDragEnd = () => {
    if (draggedIndex === null || dragOverIndex === null || draggedIndex === dragOverIndex) {
      setDraggedIndex(null)
      setDragOverIndex(null)
      return
    }

    // Reorder the tags
    const newTags = [...value]
    const [draggedTag] = newTags.splice(draggedIndex, 1)
    newTags.splice(dragOverIndex, 0, draggedTag!)

    onChange(newTags)
    setDraggedIndex(null)
    setDragOverIndex(null)
  }

  const handleDragLeave = () => {
    setDragOverIndex(null)
  }

  // Handle input key down
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      if (selectedSuggestionIndex >= 0 && filteredSuggestions.length > 0) {
        // Select suggestion
        const suggestion = filteredSuggestions[selectedSuggestionIndex]
        if (suggestion) {
          addTag(suggestion)
        }
      } else if (inputValue) {
        // Add typed tag
        addTag(inputValue)
      }
    } else if (e.key === 'Backspace' && !inputValue && value.length > 0) {
      // Remove last tag on backspace when input is empty
      e.preventDefault()
      const lastTag = value[value.length - 1]
      if (lastTag) {
        removeTag(lastTag)
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedSuggestionIndex((prev) =>
        prev < filteredSuggestions.length - 1 ? prev + 1 : prev
      )
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedSuggestionIndex((prev) => (prev > 0 ? prev - 1 : -1))
    } else if (e.key === 'Escape') {
      setShowSuggestions(false)
      setSelectedSuggestionIndex(-1)
    }
  }

  // Handle input change
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(e.target.value)
    setShowSuggestions(true)
    setSelectedSuggestionIndex(-1)
  }

  // Handle input focus
  const handleInputFocus = () => {
    if (filteredSuggestions.length > 0) {
      setShowSuggestions(true)
    }
  }

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setShowSuggestions(false)
        setSelectedSuggestionIndex(-1)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <div ref={containerRef} className="relative w-full">
      {/* Tag chips + input */}
      <div
        className={`
          flex min-h-[42px] w-full flex-wrap items-center gap-1.5 rounded-md border border-input
          bg-background px-3 py-2 text-sm ring-offset-background
          focus-within:outline-none focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2
          ${disabled ? 'cursor-not-allowed opacity-50' : ''}
          ${error ? 'border-destructive' : ''}
        `}
        onClick={() => inputRef.current?.focus()}
      >
        {/* Render existing tags with drag-to-reorder */}
        {value.map((tag, index) => {
          const isPrimary = showPrimaryIndicator && index === 0 && value.length > 1
          const isDragging = draggedIndex === index
          const isDragOver = dragOverIndex === index

          return (
            <div
              key={tag}
              draggable={!disabled && value.length > 1}
              onDragStart={(e) => handleDragStart(e, index)}
              onDragOver={(e) => handleDragOver(e, index)}
              onDragEnd={handleDragEnd}
              onDragLeave={handleDragLeave}
              className={`
                flex items-center gap-1 rounded-md px-2 py-1 transition-all
                ${!disabled && value.length > 1 ? 'cursor-move' : ''}
                ${isDragging ? 'opacity-50' : ''}
                ${isDragOver ? 'ring-2 ring-primary' : ''}
                ${isPrimary ? 'bg-primary/10 border border-primary/20' : ''}
              `}
            >
              {/* Drag handle (only show if multiple tags) */}
              {!disabled && value.length > 1 && (
                <GripVertical className="h-3 w-3 text-muted-foreground" />
              )}

              {/* Primary indicator */}
              {isPrimary && (
                <div className="flex items-center gap-1">
                  <Star className="h-3 w-3 text-primary fill-primary" />
                  <span className="text-xs font-medium text-primary">Primary</span>
                </div>
              )}

              <TagChip tag={tag} size="sm" />

              {/* Remove button */}
              {!disabled && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    removeTag(tag)
                  }}
                  className="ml-1 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
                >
                  <X className="h-3 w-3" />
                  <span className="sr-only">Remove {tag}</span>
                </button>
              )}
            </div>
          )
        })}

        {/* Input field */}
        {!disabled && value.length < maxTags && (
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            onFocus={handleInputFocus}
            placeholder={value.length === 0 ? placeholder : ''}
            className="flex-1 bg-transparent outline-none placeholder:text-muted-foreground min-w-[120px]"
            disabled={disabled}
          />
        )}

        {/* Max tags indicator */}
        {value.length >= maxTags && (
          <span className="text-xs text-muted-foreground">Max tags reached</span>
        )}
      </div>

      {/* Autocomplete suggestions dropdown */}
      {showSuggestions && filteredSuggestions.length > 0 && !disabled && (
        <div className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border bg-popover p-1 shadow-md">
          {filteredSuggestions.map((suggestion, index) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => addTag(suggestion)}
              className={`
                flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-left
                ${
                  index === selectedSuggestionIndex
                    ? 'bg-accent text-accent-foreground'
                    : 'hover:bg-accent hover:text-accent-foreground'
                }
              `}
              onMouseEnter={() => setSelectedSuggestionIndex(index)}
            >
              <TagChip tag={suggestion} size="sm" />
            </button>
          ))}
        </div>
      )}

      {/* Error message */}
      {error && (
        <p className="mt-1 text-xs text-destructive">{error}</p>
      )}

      {/* Helper text */}
      {!error && (
        <p className="mt-1 text-xs text-muted-foreground">
          {value.length}/{maxTags} tags • Press Enter to add • Backspace to remove
          {value.length > 1 && showPrimaryIndicator && ' • Drag to reorder (first tag = primary)'}
        </p>
      )}
    </div>
  )
}
