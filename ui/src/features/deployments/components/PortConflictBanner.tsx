/**
 * Warning banner listing host-port conflicts for the selected target host.
 *
 * Rendered between the host selector and the action-button row in StackEditor.
 * Hidden when there are no conflicts. Shows a neutral "check skipped" variant
 * when the validation request errors (e.g., host offline).
 */

import { AlertTriangle, Info } from 'lucide-react'

import type { PortConflict } from '../types'

interface PortConflictBannerProps {
  conflicts: PortConflict[]
  isLoading: boolean
  error: Error | null
  hostName: string
}

export function PortConflictBanner({
  conflicts,
  isLoading,
  error,
  hostName,
}: PortConflictBannerProps) {
  if (isLoading) return null

  if (error) {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 p-3 text-sm">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div className="text-muted-foreground">
          Port check skipped — unable to reach <strong>{hostName}</strong>. Deploy will still attempt normally.
        </div>
      </div>
    )
  }

  if (conflicts.length === 0) return null

  return (
    <div className="flex items-start gap-3 rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
      <div className="flex-1 space-y-1">
        <p className="font-medium text-warning">
          Port conflicts on {hostName}
        </p>
        <ul className="space-y-0.5 text-muted-foreground">
          {conflicts.map((c) => (
            <li key={`${c.port}-${c.protocol}-${c.container_id}`}>
              Port <code className="rounded bg-warning/20 px-1 text-foreground">{c.port}/{c.protocol}</code>{' '}
              is used by <strong className="text-foreground">{c.container_name}</strong>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
