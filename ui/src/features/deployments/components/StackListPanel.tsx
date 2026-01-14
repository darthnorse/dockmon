/**
 * Stack List Panel Component
 *
 * Left column of the StackModal showing:
 * - New Stack button
 * - Search input
 * - List of stacks with deployed host counts
 */

import { useState, useMemo } from 'react'
import { Search, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { StackListItem } from '../types'

interface StackListPanelProps {
  stacks: StackListItem[] | undefined
  isLoading: boolean
  selectedStackName: string | null
  isCreateMode: boolean
  onStackSelect: (name: string) => void
}

export function StackListPanel({
  stacks,
  isLoading,
  selectedStackName,
  isCreateMode,
  onStackSelect,
}: StackListPanelProps) {
  const [searchQuery, setSearchQuery] = useState('')

  // Filter stacks by search query
  const filteredStacks = useMemo(() => {
    if (!stacks) return []
    if (!searchQuery.trim()) return stacks
    return stacks.filter((s) =>
      s.name.toLowerCase().includes(searchQuery.toLowerCase())
    )
  }, [stacks, searchQuery])

  const renderStackList = () => {
    if (isLoading) {
      return <p className="text-sm text-muted-foreground p-2">Loading stacks...</p>
    }

    return (
      <>
        {filteredStacks.map((stack) => (
          <button
            key={stack.name}
            type="button"
            onClick={() => onStackSelect(stack.name)}
            className={cn(
              'w-full text-left px-3 py-2 rounded-md transition-colors flex items-center justify-between',
              selectedStackName === stack.name
                ? 'bg-primary text-primary-foreground'
                : 'hover:bg-muted'
            )}
          >
            <span className="truncate font-mono text-sm">{stack.name}</span>
            {stack.deployed_to.length > 0 && (
              <Badge
                variant={selectedStackName === stack.name ? 'secondary' : 'outline'}
                className="ml-2 shrink-0"
              >
                {stack.deployed_to.length}
              </Badge>
            )}
          </button>
        ))}

        {filteredStacks.length === 0 && stacks && stacks.length > 0 && (
          <p className="text-sm text-muted-foreground p-2">
            No stacks match "{searchQuery}"
          </p>
        )}

        {(!stacks || stacks.length === 0) && (
          <p className="text-sm text-muted-foreground p-2">
            No stacks yet. Create your first stack.
          </p>
        )}
      </>
    )
  }

  return (
    <div className="flex flex-col border-r pr-4 pt-1 pl-1 overflow-hidden">
      {/* New Stack button */}
      <Button
        variant="outline"
        size="sm"
        onClick={() => onStackSelect('__new__')}
        className={cn(
          'mb-3 gap-2 shrink-0',
          isCreateMode && 'bg-primary text-primary-foreground hover:bg-primary/90'
        )}
      >
        <Plus className="h-4 w-4" />
        New Stack
      </Button>

      {/* Search input */}
      <div className="relative mb-3 shrink-0">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search stacks..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-9"
        />
      </div>

      {/* Stack list */}
      <div className="flex-1 overflow-y-auto space-y-1">
        {renderStackList()}
      </div>
    </div>
  )
}
