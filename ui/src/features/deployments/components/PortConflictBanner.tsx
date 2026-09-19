/**
 * Warning banner listing host-port conflicts for the selected target host.
 *
 * Rendered between the host selector and the action-button row in StackEditor.
 * Hidden when there are no conflicts. A malformed compose (HTTP 400) is shown as
 * a blocking error; any other failure (host offline, network) shows a neutral
 * "check skipped" variant.
 */

import { AlertTriangle, Info } from 'lucide-react'

import { ApiError } from '@/lib/api/client'

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
    // 400 = malformed compose (the real problem), not a connectivity failure.
    if (error instanceof ApiError && error.status === 400) {
      return (
        <div className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden="true" />
          <div className="space-y-0.5">
            <p className="font-medium text-destructive">Compose file is invalid</p>
            <p className="text-muted-foreground">{error.message}</p>
          </div>
        </div>
      )
    }
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
      <div className="space-y-1">
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
