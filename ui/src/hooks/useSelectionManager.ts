/**
 * useSelectionManager - Reusable hook for managing item selection state
 *
 * Used by HostImagesTab and HostNetworksTab for bulk selection.
 *
 * Features:
 * - Track selected items by key
 * - Auto-cleanup stale selections when items change
 * - Toggle single/all selection
 * - Support for non-selectable items (e.g., built-in networks)
 */

import { useState, useMemo, useEffect, useCallback } from 'react'

interface UseSelectionManagerOptions<T> {
  /** All items (unfiltered) - used for stale selection cleanup */
  items: T[] | undefined
  /** Currently visible/filtered items */
  filteredItems: T[]
  /** Extract the selection key from an item */
  getKey: (item: T) => string
  /** Optional: determine if an item can be selected (default: all items selectable) */
  isSelectable?: (item: T) => boolean
}

interface UseSelectionManagerResult {
  /** Set of selected keys */
  selectedKeys: Set<string>
  /** Number of selected items */
  selectedCount: number
  /** Whether all selectable filtered items are selected */
  allSelected: boolean
  /** Toggle selection for a single item by key */
  toggleSelection: (key: string) => void
  /** Toggle select all for current filtered items */
  toggleSelectAll: () => void
  /** Clear all selections */
  clearSelection: () => void
  /** Check if a specific key is selected */
  isSelected: (key: string) => boolean
}

export function useSelectionManager<T>({
  items,
  filteredItems,
  getKey,
  isSelectable = () => true,
}: UseSelectionManagerOptions<T>): UseSelectionManagerResult {
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set())

  // Get all valid keys (for stale selection cleanup)
  const allValidKeys = useMemo(
    () => new Set((items ?? []).filter(isSelectable).map(getKey)),
    [items, getKey, isSelectable]
  )

  // Get selectable keys from filtered items
  const selectableFilteredKeys = useMemo(
    () => filteredItems.filter(isSelectable).map(getKey),
    [filteredItems, getKey, isSelectable]
  )

  // Clean up stale selections when items change (e.g., after deletion)
  useEffect(() => {
    setSelectedKeys((prev) => {
      const validKeys = new Set([...prev].filter((key) => allValidKeys.has(key)))
      // Only update if something was removed
      if (validKeys.size !== prev.size) {
        return validKeys
      }
      return prev
    })
  }, [allValidKeys])

  // Check if all selectable filtered items are selected
  const allSelected = useMemo(
    () => selectableFilteredKeys.length > 0 && selectableFilteredKeys.every((key) => selectedKeys.has(key)),
    [selectableFilteredKeys, selectedKeys]
  )

  // Toggle selection for a single item
  const toggleSelection = useCallback((key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }, [])

  // Toggle select all for current filtered items
  const toggleSelectAll = useCallback(() => {
    if (allSelected) {
      // Deselect all current
      setSelectedKeys((prev) => {
        const next = new Set(prev)
        selectableFilteredKeys.forEach((key) => next.delete(key))
        return next
      })
    } else {
      // Select all current
      setSelectedKeys((prev) => {
        const next = new Set(prev)
        selectableFilteredKeys.forEach((key) => next.add(key))
        return next
      })
    }
  }, [allSelected, selectableFilteredKeys])

  // Clear all selections
  const clearSelection = useCallback(() => {
    setSelectedKeys(new Set())
  }, [])

  // Check if a specific key is selected
  const isSelected = useCallback((key: string) => selectedKeys.has(key), [selectedKeys])

  return {
    selectedKeys,
    selectedCount: selectedKeys.size,
    allSelected,
    toggleSelection,
    toggleSelectAll,
    clearSelection,
    isSelected,
  }
}
