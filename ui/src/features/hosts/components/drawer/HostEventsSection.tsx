/**
 * HostEventsSection Component
 *
 * Displays recent Docker events for a host
 */

import { Calendar, ArrowRight, AlertCircle } from 'lucide-react'
import { DrawerSection } from '@/components/ui/drawer'
import { Link } from 'react-router-dom'
import { useHostEvents } from '@/hooks/useEvents'
import { formatSeverity, getSeverityColor, formatRelativeTime } from '@/lib/utils/eventUtils'
import { formatTimestamp } from '@/lib/utils/timeFormat'
import { useTimeFormat } from '@/lib/hooks/useUserPreferences'

interface HostEventsSectionProps {
  hostId: string
}

export function HostEventsSection({ hostId }: HostEventsSectionProps) {
  const { timeFormat } = useTimeFormat()
  const { data: eventsData, isLoading, error } = useHostEvents(hostId, 5)
  const events = eventsData?.events ?? []

  if (isLoading) {
    return (
      <DrawerSection title="Recent Events">
        <div className="text-center py-8 text-muted-foreground">
          <p className="text-sm">Loading events...</p>
        </div>
      </DrawerSection>
    )
  }

  if (error) {
    return (
      <DrawerSection title="Recent Events">
        <div className="text-center py-8">
          <AlertCircle className="h-12 w-12 mx-auto mb-3 text-red-500 opacity-50" />
          <p className="text-sm text-red-500">Failed to load events</p>
        </div>
      </DrawerSection>
    )
  }

  return (
    <DrawerSection title="Recent Events">
      {events.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          <Calendar className="h-12 w-12 mx-auto mb-3 opacity-50" />
          <p className="text-sm">No recent events</p>
        </div>
      ) : (
        <div className="space-y-3">
          {events.map((event) => {
            const severityColors = getSeverityColor(event.severity)
            return (
              <div
                key={event.id}
                className="p-3 rounded-lg border border-border bg-surface-1 hover:bg-surface-2 transition-colors"
              >
                <div className="flex items-start justify-between gap-2 mb-2">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium border ${severityColors.bg} ${severityColors.text} ${severityColors.border}`}
                  >
                    {formatSeverity(event.severity)}
                  </span>
                  <span
                    className="text-xs text-muted-foreground whitespace-nowrap"
                    title={formatTimestamp(event.timestamp, timeFormat)}
                  >
                    {formatRelativeTime(event.timestamp)}
                  </span>
                </div>
                <h4 className="text-sm font-medium mb-1">{event.title}</h4>
                {event.message && (
                  <p className="text-xs text-muted-foreground line-clamp-2">
                    {event.message}
                  </p>
                )}
                {event.container_name && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Container: {event.container_name}
                  </p>
                )}
              </div>
            )
          })}

          {/* View All Link */}
          <Link
            to={`/events?host_id=${hostId}`}
            className="flex items-center justify-center gap-2 p-3 rounded-lg border border-border hover:bg-muted transition-colors text-sm text-muted-foreground hover:text-foreground"
          >
            <span>View all events for this host</span>
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      )}
    </DrawerSection>
  )
}
