/**
 * EventRow Component
 *
 * Reusable component for displaying a single event with proper formatting
 * Includes colored state transitions, metadata, and timestamps
 */

import { formatTimestamp, getSeverityColor, formatSeverity } from '@/lib/utils/eventUtils'
import { makeCompositeKeyFrom } from '@/lib/utils/containerKeys'
import type { Event } from '@/types/events'

interface EventRowProps {
  event: Event
  showMetadata?: boolean
  compact?: boolean
  onContainerClick?: (compositeKey: string) => void
  onHostClick?: (hostId: string) => void
}

// Get color for state based on semantic meaning
const getStateColor = (state: string): string => {
  const stateLower = state.toLowerCase()

  // Running/healthy states - green
  if (stateLower === 'running' || stateLower === 'healthy') {
    return 'text-green-400'
  }

  // Stopped/exited states - red
  if (stateLower === 'exited' || stateLower === 'dead' || stateLower === 'unhealthy') {
    return 'text-red-400'
  }

  // Neutral/other states - gray
  return 'text-gray-400'
}

// Format message with colored state transitions
const formatMessage = (event: Event) => {
  let message = event.message || ''

  // Replace state names in the message with colored versions
  if (event.old_state && event.new_state) {
    // Handle "from X to Y" pattern
    const pattern = new RegExp(`(from\\s+)(${event.old_state})(\\s+to\\s+)(${event.new_state})`, 'i')
    if (pattern.test(message)) {
      return {
        hasStates: true,
        pattern: 'from-to',
        oldState: event.old_state,
        newState: event.new_state,
        prefix: message.match(pattern)?.[1] || 'from ',
        infix: message.match(pattern)?.[3] || ' to ',
        beforeText: message.split(pattern)[0],
        afterText: message.split(new RegExp(event.new_state, 'i'))[1] || '',
      }
    }

    // Handle "X → Y" pattern (using alternation instead of character class to avoid regex range error)
    const arrowPattern = new RegExp(`(${event.old_state})\\s*(?:→|->)\\s*(${event.new_state})`, 'i')
    if (arrowPattern.test(message)) {
      return {
        hasStates: true,
        pattern: 'arrow',
        oldState: event.old_state,
        newState: event.new_state,
        beforeText: message.split(arrowPattern)[0],
        afterText: message.split(arrowPattern)[message.split(arrowPattern).length - 1] || '',
      }
    }
  }

  return { hasStates: false, text: message }
}

// Render metadata with clickable links
const MetadataLinks = ({
  event,
  onContainerClick,
  onHostClick
}: {
  event: Event
  onContainerClick?: (id: string) => void
  onHostClick?: (id: string) => void
}) => {
  const hasContainer = event.container_name && event.container_id
  const hasHost = event.host_name && event.host_id

  if (!hasContainer && !hasHost) return null

  return (
    <div className="text-xs text-muted-foreground/70 mt-0.5 space-x-2">
      {hasContainer && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            if (event.host_id && event.container_id) {
              // Check if container_id is already a composite key (contains ':')
              // This handles mixed state where some events have composite keys, others have short IDs
              const compositeKey = event.container_id.includes(':')
                ? event.container_id // Already composite, use as-is
                : makeCompositeKeyFrom(event.host_id, event.container_id) // Short ID, create composite
              onContainerClick?.(compositeKey)
            }
          }}
          className="hover:text-primary hover:underline transition-colors"
        >
          container={event.container_name}
        </button>
      )}
      {hasHost && event.host_id && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onHostClick?.(event.host_id!)
          }}
          className="hover:text-primary hover:underline transition-colors"
        >
          host={event.host_name}
        </button>
      )}
    </div>
  )
}

export function EventRow({ event, showMetadata = true, compact = false, onContainerClick, onHostClick }: EventRowProps) {
  const severityColors = getSeverityColor(event.severity)
  const formattedMsg = formatMessage(event)

  if (compact) {
    // Compact view for cards/smaller spaces
    return (
      <div className="p-3 rounded-lg border border-border bg-surface-1 hover:bg-surface-2 transition-colors">
        <div className="flex items-start justify-between gap-2 mb-1">
          <span className={`text-xs font-medium ${severityColors.text}`}>
            {formatSeverity(event.severity)}
          </span>
          <span className="text-xs text-muted-foreground whitespace-nowrap font-mono">
            {formatTimestamp(event.timestamp)}
          </span>
        </div>
        <div className="text-sm leading-relaxed">
          <span className="text-foreground">{event.title}</span>
          {event.message && (
            <>
              {' '}
              {formattedMsg.hasStates ? (
                <>
                  {formattedMsg.beforeText}
                  {formattedMsg.pattern === 'from-to' && (
                    <>
                      {formattedMsg.prefix}
                      <span className={getStateColor(formattedMsg.oldState)}>
                        {formattedMsg.oldState}
                      </span>
                      {formattedMsg.infix}
                      <span className={getStateColor(formattedMsg.newState)}>
                        {formattedMsg.newState}
                      </span>
                      {formattedMsg.afterText}
                    </>
                  )}
                  {formattedMsg.pattern === 'arrow' && (
                    <>
                      <span className={getStateColor(formattedMsg.oldState)}>
                        {formattedMsg.oldState}
                      </span>
                      {' → '}
                      <span className={getStateColor(formattedMsg.newState)}>
                        {formattedMsg.newState}
                      </span>
                      {formattedMsg.afterText}
                    </>
                  )}
                </>
              ) : (
                <span className="text-muted-foreground">{formattedMsg.text}</span>
              )}
            </>
          )}
        </div>
        {showMetadata && (
          <MetadataLinks
            event={event}
            {...(onContainerClick && { onContainerClick })}
            {...(onHostClick && { onHostClick })}
          />
        )}
      </div>
    )
  }

  // Full view for tables
  return (
    <div className="px-6 py-2 grid grid-cols-[200px_120px_1fr] gap-4 hover:bg-surface-1 transition-colors items-start group">
      {/* Timestamp */}
      <div className="text-sm font-mono text-muted-foreground pt-0.5">
        {formatTimestamp(event.timestamp)}
      </div>

      {/* Severity */}
      <div className="pt-0.5">
        <span className={`text-sm font-medium ${severityColors.text}`}>
          {formatSeverity(event.severity)}
        </span>
      </div>

      {/* Event Details */}
      <div className="flex items-start justify-between gap-4 min-w-0">
        <div className="flex-1 min-w-0">
          {/* Main message with inline colored states */}
          <div className="text-sm leading-relaxed">
            <span className="text-foreground">{event.title}</span>
            {event.message && (
              <>
                {' '}
                {formattedMsg.hasStates ? (
                  <>
                    {formattedMsg.beforeText}
                    {formattedMsg.pattern === 'from-to' && (
                      <>
                        {formattedMsg.prefix}
                        <span className={getStateColor(formattedMsg.oldState)}>
                          {formattedMsg.oldState}
                        </span>
                        {formattedMsg.infix}
                        <span className={getStateColor(formattedMsg.newState)}>
                          {formattedMsg.newState}
                        </span>
                        {formattedMsg.afterText}
                      </>
                    )}
                    {formattedMsg.pattern === 'arrow' && (
                      <>
                        <span className={getStateColor(formattedMsg.oldState)}>
                          {formattedMsg.oldState}
                        </span>
                        {' → '}
                        <span className={getStateColor(formattedMsg.newState)}>
                          {formattedMsg.newState}
                        </span>
                        {formattedMsg.afterText}
                      </>
                    )}
                  </>
                ) : (
                  <span className="text-muted-foreground">{formattedMsg.text}</span>
                )}
              </>
            )}
          </div>

          {/* Metadata */}
          {showMetadata && (
            <MetadataLinks
              event={event}
              {...(onContainerClick && { onContainerClick })}
              {...(onHostClick && { onHostClick })}
            />
          )}
        </div>
      </div>
    </div>
  )
}
