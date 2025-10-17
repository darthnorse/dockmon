/**
 * WebSocket Provider - Phase 3b
 *
 * FEATURES:
 * - Single WebSocket connection for entire app
 * - Event subscription system
 * - Automatic reconnection with exponential backoff
 * - React Context for easy access
 * - Automatic query invalidation on server events
 *
 * ARCHITECTURE:
 * - Provider wraps authenticated routes
 * - useWebSocketContext hook for consumers
 * - Event-driven updates trigger TanStack Query invalidation
 *
 * MESSAGE TYPES (from backend):
 * - initial_state: Sent on connection with hosts, containers, settings
 * - containers_update: Container status/metrics changed
 * - new_event: New event logged (Docker events)
 * - container_stats: Real-time container statistics
 * - host_added: New Docker host added
 * - host_removed: Docker host removed
 * - auto_restart_success: Container auto-restart succeeded
 * - auto_restart_failed: Container auto-restart failed
 * - blackout_status_changed: Notification blackout status changed
 * - pong: Heartbeat response
 */

import { createContext, useContext, useCallback, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { debug } from '@/lib/debug'
import { useWebSocket, type WebSocketMessage, type WebSocketStatus } from './useWebSocket'

type MessageHandler = (message: WebSocketMessage) => void

interface WebSocketContextValue {
  status: WebSocketStatus
  send: (data: unknown) => void
  addMessageHandler: (handler: MessageHandler) => () => void
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null)

export function useWebSocketContext() {
  const context = useContext(WebSocketContext)
  if (!context) {
    throw new Error('useWebSocketContext must be used within WebSocketProvider')
  }
  return context
}

interface WebSocketProviderProps {
  children: React.ReactNode
}

export function WebSocketProvider({ children }: WebSocketProviderProps) {
  const queryClient = useQueryClient()
  const messageHandlersRef = useRef<Set<MessageHandler>>(new Set())

  // Register a custom message handler
  const addMessageHandler = useCallback((handler: MessageHandler) => {
    messageHandlersRef.current.add(handler)
    debug.log('WebSocket', 'Added message handler (total:', messageHandlersRef.current.size, ')')

    // Return cleanup function
    return () => {
      messageHandlersRef.current.delete(handler)
      debug.log('WebSocket', 'Removed message handler (total:', messageHandlersRef.current.size, ')')
    }
  }, [])

  // Handle WebSocket messages
  const handleMessage = useCallback(
    (message: WebSocketMessage) => {
      debug.log('WebSocket', 'Received message:', message.type)

      // Notify all custom handlers first
      messageHandlersRef.current.forEach((handler) => {
        try {
          handler(message)
        } catch (error) {
          debug.error('WebSocket', 'Message handler error:', error)
        }
      })

      // Then handle query invalidation
      switch (message.type) {
        // Initial state sent on connection
        case 'initial_state':
          debug.log('WebSocket', 'Received initial state')
          queryClient.invalidateQueries({ queryKey: ['containers'] })
          queryClient.invalidateQueries({ queryKey: ['hosts'] })
          break

        // Container status/metrics updates
        case 'containers_update':
          queryClient.invalidateQueries({ queryKey: ['containers'] })
          // Also invalidate dashboard hosts for sparkline updates (Phase 4c)
          queryClient.invalidateQueries({ queryKey: ['dashboard', 'hosts'] })
          break

        // Real-time container statistics
        case 'container_stats':
          // Stats are handled by individual widgets with refetchInterval
          // No need to invalidate queries here - prevents cascade of 60+ requests/min
          // Individual components manage their own stat updates via StatsProvider
          break

        // New Docker event logged
        case 'new_event':
          queryClient.invalidateQueries({ queryKey: ['events'] })
          break

        // Host management events
        case 'host_added':
        case 'host_removed':
          queryClient.invalidateQueries({ queryKey: ['hosts'] })
          queryClient.invalidateQueries({ queryKey: ['containers'] })
          break

        // Host status change (online/offline) - Real-time dashboard updates
        case 'host_status_changed':
          queryClient.invalidateQueries({ queryKey: ['hosts'] })
          queryClient.invalidateQueries({ queryKey: ['dashboard', 'hosts'] })
          break

        // Auto-restart events
        case 'auto_restart_success':
        case 'auto_restart_failed':
          queryClient.invalidateQueries({ queryKey: ['containers'] })
          queryClient.invalidateQueries({ queryKey: ['events'] })
          break

        // Notification blackout status changed
        case 'blackout_status_changed':
          queryClient.invalidateQueries({ queryKey: ['settings'] })
          break

        // Batch job updates (handled by BatchJobPanel component)
        case 'batch_job_update':
        case 'batch_item_update':
          // These are handled by the BatchJobPanel component via addMessageHandler
          break

        // Heartbeat response (no action needed)
        case 'pong':
          break

        // Exhaustive check: all message types are handled
        // If a new message type is added to the backend, TypeScript will error here
        default: {
          const exhaustiveCheck: never = message
          debug.warn('WebSocket', 'Unhandled message type:', exhaustiveCheck)
          break
        }
      }
    },
    [queryClient]
  )

  // Determine WebSocket URL dynamically based on current host and protocol
  const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/`

  const { status, send } = useWebSocket({
    url: wsUrl,
    onMessage: handleMessage,
    onConnect: () => {
      debug.log('WebSocket', '✅ Connected')
    },
    onDisconnect: () => {
      debug.log('WebSocket', '❌ Disconnected')
    },
    onError: (error) => {
      debug.error('WebSocket', 'Connection error:', error)
    },
    reconnect: true,
    reconnectInterval: 3000,
    reconnectAttempts: 10,
  })

  return (
    <WebSocketContext.Provider value={{ status, send, addMessageHandler }}>
      {children}
    </WebSocketContext.Provider>
  )
}
