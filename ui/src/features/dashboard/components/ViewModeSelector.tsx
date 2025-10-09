/**
 * ViewModeSelector - Phase 4b
 *
 * Segmented control for switching dashboard view modes
 * Compact | Standard | Expanded
 */

import { LayoutGrid, LayoutList, Maximize2 } from 'lucide-react'
import { ViewMode } from '../hooks/useViewMode'
import { cn } from '@/lib/utils'

interface ViewModeSelectorProps {
  viewMode: ViewMode
  onChange: (mode: ViewMode) => void
  disabled?: boolean
}

export function ViewModeSelector({ viewMode, onChange, disabled = false }: ViewModeSelectorProps) {
  const modes: Array<{ value: ViewMode; label: string; icon: React.ReactNode }> = [
    { value: 'compact', label: 'Compact', icon: <LayoutGrid className="h-4 w-4" /> },
    { value: 'standard', label: 'Standard', icon: <LayoutList className="h-4 w-4" /> },
    { value: 'expanded', label: 'Expanded', icon: <Maximize2 className="h-4 w-4" /> },
  ]

  return (
    <div
      role="radiogroup"
      aria-label="Dashboard view mode"
      className="inline-flex items-center gap-1 p-1 bg-muted rounded-lg"
    >
      {modes.map((mode) => {
        const isActive = viewMode === mode.value

        return (
          <button
            key={mode.value}
            type="button"
            role="radio"
            aria-checked={isActive}
            aria-label={`${mode.label} view mode`}
            disabled={disabled}
            onClick={() => onChange(mode.value)}
            className={cn(
              'inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              isActive
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
            )}
          >
            {mode.icon}
            <span className="hidden sm:inline">{mode.label}</span>
          </button>
        )
      })}
    </div>
  )
}
