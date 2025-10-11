/**
 * HostLogsTab Component
 *
 * Logs tab for host modal - Docker daemon logs
 */

interface HostLogsTabProps {
  hostId: string
}

export function HostLogsTab({}: HostLogsTabProps) {
  return (
    <div className="p-6">
      <div className="bg-surface-2 rounded-lg border border-border p-8 text-center">
        <p className="text-muted-foreground">
          Host logs feature coming soon
        </p>
      </div>
    </div>
  )
}
