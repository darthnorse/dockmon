/**
 * HostMultiSelect Component
 *
 * Multi-select autocomplete input for selecting hosts
 * Similar to TagInput but optimized for host selection
 */

import { useState, useRef, useEffect } from 'react'
import { X, ChevronDown, Server } from 'lucide-react'
import type { Host } from '@/types/api'

export interface HostMultiSelectProps {
  hosts: Host[]
  selectedHostIds: string[]
  onChange: (hostIds: string[]) => void
  placeholder?: string
  disabled?: boolean
}

export function HostMultiSelect({
  hosts,
  selectedHostIds,
  onChange,
  placeholder = 'Select hosts...',
  disabled = false,
}: HostMultiSelectProps) {
  const [inputValue, setInputValue] = useState('')
  const [showDropdown, setShowDropdown] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Get selected hosts
  const selectedHosts = hosts.filter((h) => selectedHostIds.includes(h.id))

  // Filter hosts based on input and exclude already selected
  const filteredHosts = hosts
    .filter((h) => !selectedHostIds.includes(h.id))
    .filter((h) =>
      h.name.toLowerCase().includes(inputValue.toLowerCase()) ||
      (h.url && h.url.toLowerCase().includes(inputValue.toLowerCase()))
    )
    .slice(0, 10) // Max 10 suggestions

  // Handle host selection
  const selectHost = (hostId: string) => {
    onChange([...selectedHostIds, hostId])
    setInputValue('')
    setShowDropdown(false)
    setSelectedIndex(-1)
    inputRef.current?.focus()
  }

  // Handle host removal
  const removeHost = (hostId: string) => {
    onChange(selectedHostIds.filter((id) => id !== hostId))
  }

  // Handle keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setShowDropdown(false)
      setSelectedIndex(-1)
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setShowDropdown(true)
      setSelectedIndex((prev) => Math.min(prev + 1, filteredHosts.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex((prev) => Math.max(prev - 1, -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const selectedHost = filteredHosts[selectedIndex]
      if (selectedIndex >= 0 && selectedIndex < filteredHosts.length && selectedHost) {
        selectHost(selectedHost.id)
      }
    } else if (e.key === 'Backspace' && !inputValue && selectedHostIds.length > 0) {
      // Remove last host on backspace if input is empty
      const lastHostId = selectedHostIds[selectedHostIds.length - 1]
      if (lastHostId) {
        removeHost(lastHostId)
      }
    }
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setShowDropdown(false)
        setSelectedIndex(-1)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Scroll selected item into view
  useEffect(() => {
    if (selectedIndex >= 0) {
      const element = document.getElementById(`host-option-${selectedIndex}`)
      element?.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedIndex])

  return (
    <div ref={containerRef} className="relative">
      <div
        className={`flex flex-wrap gap-2 p-2 rounded-lg border ${
          disabled ? 'bg-muted cursor-not-allowed' : 'bg-surface-1 cursor-text'
        } ${showDropdown ? 'ring-2 ring-primary' : 'border-border'}`}
        onClick={() => !disabled && inputRef.current?.focus()}
      >
        {/* Selected Hosts */}
        {selectedHosts.map((host) => (
          <div
            key={host.id}
            className="flex items-center gap-1.5 px-2 py-1 rounded bg-primary/20 text-primary text-sm"
          >
            <Server className="h-3 w-3" />
            <span>{host.name}</span>
            {!disabled && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  removeHost(host.id)
                }}
                className="hover:bg-primary/30 rounded p-0.5 transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        ))}

        {/* Input */}
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value)
            setShowDropdown(true)
            setSelectedIndex(-1)
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => setShowDropdown(true)}
          placeholder={selectedHostIds.length === 0 ? placeholder : ''}
          disabled={disabled}
          className="flex-1 min-w-[120px] bg-transparent outline-none text-sm disabled:cursor-not-allowed"
        />

        {/* Dropdown Icon */}
        <button
          onClick={(e) => {
            e.stopPropagation()
            setShowDropdown(!showDropdown)
            inputRef.current?.focus()
          }}
          disabled={disabled}
          className="p-1 rounded hover:bg-surface-2 transition-colors disabled:opacity-50"
        >
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        </button>
      </div>

      {/* Dropdown */}
      {showDropdown && !disabled && filteredHosts.length > 0 && (
        <div className="absolute z-50 w-full mt-1 py-1 rounded-lg border border-border bg-surface shadow-lg max-h-[300px] overflow-y-auto">
          {filteredHosts.map((host, index) => (
            <button
              key={host.id}
              id={`host-option-${index}`}
              onClick={() => selectHost(host.id)}
              className={`w-full px-3 py-2 text-left text-sm flex items-center gap-2 transition-colors ${
                index === selectedIndex
                  ? 'bg-primary/20 text-primary'
                  : 'hover:bg-surface-2'
              }`}
            >
              <Server className="h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{host.name}</div>
                {host.url && (
                  <div className="text-xs text-muted-foreground truncate">{host.url}</div>
                )}
              </div>
            </button>
          ))}
        </div>
      )}

      {/* No Results Message */}
      {showDropdown && !disabled && inputValue && filteredHosts.length === 0 && (
        <div className="absolute z-50 w-full mt-1 py-2 px-3 rounded-lg border border-border bg-surface shadow-lg text-sm text-muted-foreground">
          No matching hosts found
        </div>
      )}
    </div>
  )
}
