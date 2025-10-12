/**
 * ContainerEventsTab Component
 *
 * Events tab for container drawer - Shows events for specific container
 */

import { Calendar, AlertCircle, ArrowRight } from 'lucide-react'
import { useContainerEvents } from '@/hooks/useEvents'

interface ContainerEventsTabProps {
  hostId: string
  containerId: string
}

export function ContainerEventsTab({ hostId, containerId }: ContainerEventsTabProps) {
  const { data: eventsData, isLoading, error } = useContainerEvents(hostId, containerId, 50)
  const events = eventsData?.events ?? []

  if (isLoading) {
    return (
      <div className="p-4">
        <div className="text-center py-8 text-muted-foreground">
          <p className="text-sm">Loading events...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4">
        <div className="text-center py-8">
          <AlertCircle className="h-12 w-12 mx-auto mb-3 text-red-500 opacity-50" />
          <p className="text-sm text-red-500">Failed to load events</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {events.length === 0 ? (
        <div className="flex items-center justify-center flex-1">
          <div className="text-center py-8 text-muted-foreground">
            <Calendar className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p className="text-sm">No events found for this container</p>
          </div>
        </div>
      ) : (
        <>
          {/* Compact event list - no table header for drawer */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {events.map((event) => {
              const severityColors = {
                critical: 'text-red-500',
                error: 'text-red-400',
                warning: 'text-yellow-500',
                info: 'text-blue-400',
              }[event.severity.toLowerCase()] || 'text-gray-400'

              return (
                <div
                  key={event.id}
                  className="p-3 rounded-lg border border-border bg-surface-1 hover:bg-surface-2 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2 mb-1">
                    <span className={`text-xs font-medium ${severityColors}`}>
                      {event.severity.charAt(0).toUpperCase() + event.severity.slice(1)}
                    </span>
                    <span className="text-xs text-muted-foreground whitespace-nowrap font-mono">
                      {new Date(event.timestamp).toLocaleString('en-US', {
                        month: 'numeric',
                        day: 'numeric',
                        year: 'numeric',
                        hour: 'numeric',
                        minute: '2-digit',
                        hour12: true,
                      })}
                    </span>
                  </div>
                  <div className="text-sm">{event.title}</div>
                  {event.message && (
                    <div className="text-xs text-muted-foreground mt-1 line-clamp-3">
                      {event.message}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* View in Modal Link */}
          <div className="border-t border-border p-3">
            <button
              onClick={() => {
                // TODO: Open container modal to Events tab
                console.log('Open container modal events tab')
              }}
              className="w-full flex items-center justify-center gap-2 p-2 rounded-lg border border-border hover:bg-muted transition-colors text-sm text-muted-foreground hover:text-foreground"
            >
              <span>View all in container modal</span>
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </>
      )}
    </div>
  )
}
