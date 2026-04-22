import { VIEWS } from '@/lib/statsConfig'
import type { TimeRange } from './historyTypes'

const RANGES: { value: TimeRange; label: string }[] = [
  { value: 'live', label: 'Live' },
  ...VIEWS.map((v) => ({ value: v.name, label: v.label })),
]

interface Props {
  value: TimeRange
  onChange: (range: TimeRange) => void
}

/**
 * Horizontal row of pill buttons for selecting a stats time range.
 * The "Live" option shows a pulsing green indicator when active.
 */
export function StatsTimeRangeSelector({ value, onChange }: Props) {
  return (
    <div className="flex flex-wrap gap-1" role="group" aria-label="Stats time range">
      {RANGES.map((r) => {
        const active = r.value === value
        return (
          <button
            key={r.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(r.value)}
            className={
              'inline-flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ' +
              (active
                ? 'bg-primary text-primary-foreground'
                : 'bg-surface-2 text-muted-foreground hover:bg-surface-1')
            }
          >
            {r.value === 'live' && active && (
              <span
                data-testid="live-indicator"
                className="inline-block w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse"
              />
            )}
            {r.label}
          </button>
        )
      })}
    </div>
  )
}
