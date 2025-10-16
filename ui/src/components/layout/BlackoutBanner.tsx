/**
 * Blackout Banner - Alert Suppression Notification
 *
 * Displays a banner at the top of the app when a blackout window is active.
 * Listens for blackout_status_changed WebSocket messages to show/hide in real-time.
 */

import { useState, useEffect } from 'react'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import { MoonStar, X } from 'lucide-react'

export function BlackoutBanner() {
  const [isBlackout, setIsBlackout] = useState(false)
  const [isDismissed, setIsDismissed] = useState(false)
  const { addMessageHandler } = useWebSocketContext()

  // Listen for blackout status changes and initial state
  useEffect(() => {
    const cleanup = addMessageHandler((message) => {
      // Handle initial state with blackout info
      if (message.type === 'initial_state') {
        const data = message.data as { blackout?: { is_active: boolean; window_name: string | null } }
        if (data.blackout) {
          setIsBlackout(data.blackout.is_active)
        }
      }

      // Handle blackout status changes
      if (message.type === 'blackout_status_changed') {
        const data = message.data as { is_blackout: boolean; window_name: string | null }
        setIsBlackout(data.is_blackout)

        // Reset dismissed state when blackout status changes
        if (data.is_blackout) {
          setIsDismissed(false)
        }
      }
    })

    return cleanup
  }, [addMessageHandler])

  // Don't show banner if not in blackout or dismissed
  if (!isBlackout || isDismissed) {
    return null
  }

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 pointer-events-none">
      <div className="pointer-events-auto flex items-center gap-2 px-3 py-1.5 bg-yellow-600/90 border border-yellow-500/50 rounded-full backdrop-blur-sm shadow-lg">
        <MoonStar className="h-3.5 w-3.5 text-yellow-200 flex-shrink-0" />
        <span className="text-xs font-medium text-yellow-100">
          Blackout Window Active
        </span>
        <button
          onClick={() => setIsDismissed(true)}
          className="flex items-center justify-center h-4 w-4 rounded-full hover:bg-yellow-500/30 transition-colors flex-shrink-0 ml-1"
          aria-label="Dismiss"
        >
          <X className="h-3 w-3 text-yellow-200" />
        </button>
      </div>
    </div>
  )
}
