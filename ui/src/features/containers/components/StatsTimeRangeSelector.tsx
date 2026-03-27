import type { TimeRange } from '../hooks/useStatsHistory'

const RANGES: { value: TimeRange; label: string }[] = [
  { value: 'live', label: 'Live' },
  { value: '1h', label: '1h' },
  { value: '8h', label: '8h' },
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
]

interface StatsTimeRangeSelectorProps {
  value: TimeRange
  onChange: (range: TimeRange) => void
}

export function StatsTimeRangeSelector({ value, onChange }: StatsTimeRangeSelectorProps) {
  return (
    <div className="flex gap-1">
      {RANGES.map((r) => (
        <button
          key={r.value}
          onClick={() => onChange(r.value)}
          className={`px-2 py-1 text-xs rounded transition-colors ${
            value === r.value
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted/50 text-muted-foreground hover:bg-muted'
          }`}
        >
          {r.value === 'live' && value === 'live' && (
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400 mr-1 animate-pulse" />
          )}
          {r.label}
        </button>
      ))}
    </div>
  )
}
