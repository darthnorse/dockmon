/**
 * Migration Banner - Host Migration Notification
 *
 * Displays a banner when a remote host is migrated from mTLS to agent-based connection.
 * Listens for host_migrated WebSocket messages and auto-dismisses after 30 seconds.
 */

import { useState, useEffect } from 'react'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import { ArrowRight, X } from 'lucide-react'

interface MigrationData {
  old_host_name: string
  new_host_name: string
  old_host_id: string
  new_host_id: string
}

export function MigrationBanner() {
  const [migrationData, setMigrationData] = useState<MigrationData | null>(null)
  const [isDismissed, setIsDismissed] = useState(false)
  const { addMessageHandler } = useWebSocketContext()

  // Listen for migration events
  useEffect(() => {
    let timeoutId: NodeJS.Timeout | null = null

    const cleanup = addMessageHandler((message) => {
      if (message.type === 'host_migrated') {
        const data = message.data as MigrationData
        setMigrationData(data)
        setIsDismissed(false)

        // Clear previous timeout if exists
        if (timeoutId) {
          clearTimeout(timeoutId)
        }

        // Auto-dismiss after 30 seconds
        timeoutId = setTimeout(() => {
          setIsDismissed(true)
          timeoutId = null
        }, 30000)
      }
    })

    return () => {
      cleanup()
      // Clean up timeout on unmount to prevent memory leak
      if (timeoutId) {
        clearTimeout(timeoutId)
      }
    }
  }, [addMessageHandler])

  // Don't show banner if no migration or dismissed
  if (!migrationData || isDismissed) {
    return null
  }

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 pointer-events-none max-w-xl">
      <div className="pointer-events-auto flex items-center gap-2 px-4 py-2 bg-blue-600/90 border border-blue-500/50 rounded-lg backdrop-blur-sm shadow-lg">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className="text-sm font-medium text-blue-100 truncate">
            {migrationData.old_host_name}
          </span>
          <ArrowRight className="h-4 w-4 text-blue-200 flex-shrink-0" />
          <span className="text-sm font-medium text-blue-100 truncate">
            {migrationData.new_host_name}
          </span>
        </div>
        <span className="text-xs text-blue-200 flex-shrink-0 hidden sm:block">
          Migrated to agent
        </span>
        <button
          onClick={() => setIsDismissed(true)}
          className="flex items-center justify-center h-5 w-5 rounded-full hover:bg-blue-500/30 transition-colors flex-shrink-0 ml-1"
          aria-label="Dismiss"
        >
          <X className="h-3.5 w-3.5 text-blue-200" />
        </button>
      </div>
    </div>
  )
}
