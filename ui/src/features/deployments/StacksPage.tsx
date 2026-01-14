/**
 * Stacks Page (v2.2.8+)
 *
 * Main page for managing Docker Compose stacks.
 * - List stacks with deployed hosts (from container labels)
 * - Sortable columns with localStorage persistence
 * - Click stack or "New Stack" to open consolidated StackModal
 * - All operations (edit, rename, clone, delete, deploy) happen in modal
 */

import { useState, useMemo, useEffect } from 'react'
import { Plus, AlertCircle, Layers, ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { useStacks } from './hooks/useStacks'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import { StackModal } from './components/StackModal'
import type { StackListItem } from './types'

// Sort configuration
type SortColumn = 'name' | 'deployedTo'
type SortDirection = 'asc' | 'desc'

interface SortConfig {
  column: SortColumn
  direction: SortDirection
}

const STORAGE_KEY = 'dockmon-stacks-sort'
const DEFAULT_SORT: SortConfig = { column: 'name', direction: 'asc' }

// Load sort config from localStorage
function loadSortConfig(): SortConfig {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const parsed = JSON.parse(saved)
      if (parsed.column && parsed.direction) {
        return parsed as SortConfig
      }
    }
  } catch {
    // Ignore parse errors
  }
  return DEFAULT_SORT
}

// Save sort config to localStorage
function saveSortConfig(config: SortConfig): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
  } catch {
    // Ignore storage errors
  }
}

export function StacksPage() {
  const [showStackModal, setShowStackModal] = useState(false)
  const [selectedStackName, setSelectedStackName] = useState<string | null>(null)
  const [sortConfig, setSortConfig] = useState<SortConfig>(loadSortConfig)

  const { data: stacks, isLoading, error } = useStacks()
  const { data: hosts } = useHosts()

  // Save sort config when it changes
  useEffect(() => {
    saveSortConfig(sortConfig)
  }, [sortConfig])

  // Sort stacks
  const sortedStacks = useMemo(() => {
    if (!stacks) return []

    return [...stacks].sort((a, b) => {
      let comparison = 0

      if (sortConfig.column === 'name') {
        comparison = a.name.localeCompare(b.name)
      } else if (sortConfig.column === 'deployedTo') {
        // Sort by number of hosts deployed to
        comparison = a.deployed_to.length - b.deployed_to.length
      }

      return sortConfig.direction === 'desc' ? -comparison : comparison
    })
  }, [stacks, sortConfig])

  // Handle column header click
  const handleSort = (column: SortColumn) => {
    setSortConfig((prev) => {
      if (prev.column === column) {
        // Toggle direction
        return { column, direction: prev.direction === 'asc' ? 'desc' : 'asc' }
      }
      // New column, default to ascending
      return { column, direction: 'asc' }
    })
  }

  // Get sort icon for a column
  const getSortIcon = (column: SortColumn) => {
    if (sortConfig.column !== column) {
      return <ArrowUpDown className="h-4 w-4 opacity-30" />
    }
    return sortConfig.direction === 'asc' ? (
      <ArrowUp className="h-4 w-4" />
    ) : (
      <ArrowDown className="h-4 w-4" />
    )
  }

  const handleOpenStack = (stack: StackListItem) => {
    setSelectedStackName(stack.name)
    setShowStackModal(true)
  }

  const handleNewStack = () => {
    setSelectedStackName(null)
    setShowStackModal(true)
  }

  const handleCloseModal = () => {
    setShowStackModal(false)
    setSelectedStackName(null)
  }

  return (
    <div className="p-3 sm:p-4 md:p-6 pt-16 md:pt-6 space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold">Stacks</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage and deploy Docker Compose configurations
          </p>
        </div>

        <Button
          data-testid="new-stack-button"
          onClick={handleNewStack}
          className="gap-2"
        >
          <Plus className="h-4 w-4" />
          New Stack
        </Button>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <p className="text-muted-foreground">Loading stacks...</p>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="flex items-center gap-2 p-4 bg-destructive/10 text-destructive rounded-lg">
          <AlertCircle className="h-5 w-5" />
          <p>Failed to load stacks: {error.message}</p>
        </div>
      )}

      {/* Stacks Table */}
      {!isLoading && !error && (
        <div className="rounded-lg border" data-testid="stack-list">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead
                  className="cursor-pointer select-none hover:bg-muted/50"
                  onClick={() => handleSort('name')}
                >
                  <div className="flex items-center gap-2">
                    Name
                    {getSortIcon('name')}
                  </div>
                </TableHead>
                <TableHead
                  className="cursor-pointer select-none hover:bg-muted/50"
                  onClick={() => handleSort('deployedTo')}
                >
                  <div className="flex items-center gap-2">
                    Deployed To
                    {getSortIcon('deployedTo')}
                  </div>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedStacks.length === 0 && (
                <TableRow>
                  <TableCell colSpan={2} className="text-center py-12 text-muted-foreground">
                    <div className="flex flex-col items-center gap-3">
                      <Layers className="h-10 w-10 opacity-30" />
                      <div>
                        <p className="font-medium">No stacks yet</p>
                        <p className="text-sm">Create your first stack to get started</p>
                      </div>
                      <Button
                        variant="outline"
                        onClick={handleNewStack}
                        className="gap-2 mt-2"
                      >
                        <Plus className="h-4 w-4" />
                        Create Stack
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )}

              {sortedStacks.map((stack) => (
                <TableRow
                  key={stack.name}
                  data-testid={`stack-${stack.name}`}
                  className="cursor-pointer hover:bg-muted/50"
                  onClick={() => handleOpenStack(stack)}
                >
                  {/* Name */}
                  <TableCell className="font-medium font-mono">
                    {stack.name}
                  </TableCell>

                  {/* Deployed Hosts - from container labels */}
                  <TableCell>
                    {stack.deployed_to.length > 0 ? (
                      <div className="flex flex-wrap gap-1">
                        {stack.deployed_to.map((host) => (
                          <Badge key={host.host_id} variant="secondary">
                            {host.host_name}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <span className="text-muted-foreground text-sm">Not deployed</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Stack Modal */}
      <StackModal
        isOpen={showStackModal}
        onClose={handleCloseModal}
        hosts={(hosts || []).map(h => ({ id: h.id, name: h.name || h.id }))}
        initialStackName={selectedStackName}
      />
    </div>
  )
}
