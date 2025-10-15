/**
 * GroupBySelector - Dashboard grouping control
 *
 * Dropdown selector for choosing how to group dashboard hosts:
 * - None (default grid view)
 * - By Tag (grouped by primary tag)
 */

import { ChevronDown, Check } from 'lucide-react'
import { DropdownMenu, DropdownMenuItem } from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

export type GroupByMode = 'none' | 'tags'

interface GroupBySelectorProps {
  value: GroupByMode
  onChange: (mode: GroupByMode) => void
  disabled?: boolean
}

const options: Array<{ value: GroupByMode; label: string }> = [
  { value: 'none', label: 'None' },
  { value: 'tags', label: 'Tag' },
]

export function GroupBySelector({ value, onChange, disabled = false }: GroupBySelectorProps) {
  const selectedOption = options.find((opt) => opt.value === value) ?? options[0]

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm font-medium text-muted-foreground">Group by:</span>
      <DropdownMenu
        trigger={
          <button
            type="button"
            disabled={disabled}
            className={cn(
              'inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium border border-border bg-background',
              'hover:bg-accent transition-colors',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'min-w-[120px] justify-between'
            )}
          >
            <span>{selectedOption?.label ?? 'None'}</span>
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          </button>
        }
        align="start"
      >
        <div className="py-1">
          {options.map((option) => (
            <DropdownMenuItem
              key={option.value}
              onClick={() => onChange(option.value)}
              icon={value === option.value ? <Check className="h-3.5 w-3.5" /> : undefined}
            >
              {option.label}
            </DropdownMenuItem>
          ))}
        </div>
      </DropdownMenu>
    </div>
  )
}
