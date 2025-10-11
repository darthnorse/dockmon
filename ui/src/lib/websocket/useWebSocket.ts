/**
 * WebSocket Hook - Phase 3b
 *
 * FEATURES:
 * - Auto-reconnect on disconnect
 * - Event-based message handling
 * - Connection state tracking
 * - Automatic cleanup
 * - Exponential backoff reconnection strategy
 *
 * ARCHITECTURE:
 * - Single WebSocket connection per app
 * - Multiple subscribers via event handlers
 * - Type-safe message handling
 *
 * MESSAGE TYPES:
 * Backend sends these message types (aligned with backend/main.py, backend/docker_monitor/, etc.):
 * - initial_state: Initial data on connection
 * - containers_update: Container status/metrics changed
 * - container_stats: Real-time container statistics
 * - new_event: New Docker event logged
 * - host_added/host_removed: Host management
 * - auto_restart_success/auto_restart_failed: Auto-restart events
 * - blackout_status_changed: Notification blackout toggled
 * - pong: Heartbeat response
 */

import { useEffect, useRef, useCallback, useState } from 'react'
import { debug } from '@/lib/debug'
import { POLLING_CONFIG } from '@/lib/config/polling'

/**
 * WebSocket message type definitions
 * These types match the backend message format exactly
 */
export type WebSocketMessage =
  | { type: 'initial_state'; data: unknown }
  | { type: 'containers_update'; data: unknown }
  | { type: 'container_stats'; data: unknown }
  | { type: 'new_event'; data: unknown }
  | { type: 'host_added'; data: unknown }
  | { type: 'host_removed'; data: unknown }
  | { type: 'auto_restart_success'; data: unknown }
  | { type: 'auto_restart_failed'; data: unknown }
  | { type: 'blackout_status_changed'; data: unknown }
  | { type: 'batch_job_update'; data: unknown }
  | { type: 'batch_item_update'; data: unknown }
  | { type: 'pong'; data?: unknown }

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

interface UseWebSocketOptions {
  url: string
  onMessage?: (message: WebSocketMessage) => void
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: (error: Event) => void
  reconnect?: boolean
  reconnectInterval?: number
  reconnectAttempts?: number
}

export function useWebSocket({
  url,
  onMessage,
  onConnect,
  onDisconnect,
  onError,
  reconnect = true,
  reconnectInterval = POLLING_CONFIG.WEBSOCKET_RECONNECT,
  reconnectAttempts = POLLING_CONFIG.WEBSOCKET_MAX_ATTEMPTS,
}: UseWebSocketOptions) {
  const [status, setStatus] = useState<WebSocketStatus>('connecting')
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectCountRef = useRef(0)

  // Store callbacks in refs to avoid dependency changes
  const onMessageRef = useRef(onMessage)
  const onConnectRef = useRef(onConnect)
  const onDisconnectRef = useRef(onDisconnect)
  const onErrorRef = useRef(onError)

  // Update refs when callbacks change
  useEffect(() => {
    onMessageRef.current = onMessage
    onConnectRef.current = onConnect
    onDisconnectRef.current = onDisconnect
    onErrorRef.current = onError
  }, [onMessage, onConnect, onDisconnect, onError])

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return // Already connected
    }

    try {
      setStatus('connecting')
      const ws = new WebSocket(url)

      ws.onopen = () => {
        setStatus('connected')
        reconnectCountRef.current = 0
        onConnectRef.current?.()
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as WebSocketMessage
          onMessageRef.current?.(message)
        } catch (error) {
          debug.error('WebSocket', 'Failed to parse message:', error)
        }
      }

      ws.onerror = (error) => {
        setStatus('error')
        onErrorRef.current?.(error)
      }

      ws.onclose = () => {
        setStatus('disconnected')
        onDisconnectRef.current?.()

        // Attempt reconnection
        if (reconnect && reconnectCountRef.current < reconnectAttempts) {
          reconnectCountRef.current++
          // Cap the exponent to prevent overflow after many attempts
          const cappedExponent = Math.min(reconnectCountRef.current - 1, 10)
          const baseDelay = reconnectInterval * Math.pow(1.5, cappedExponent)
          const delay = Math.min(baseDelay, POLLING_CONFIG.WEBSOCKET_MAX_DELAY)

          reconnectTimeoutRef.current = setTimeout(() => {
            debug.log(
              'WebSocket',
              `Reconnecting (attempt ${reconnectCountRef.current}/${reconnectAttempts})...`
            )
            connect()
          }, delay)
        }
      }

      wsRef.current = ws
    } catch (error) {
      debug.error('WebSocket', 'Connection failed:', error)
      setStatus('error')
    }
  }, [url, reconnect, reconnectInterval, reconnectAttempts])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    setStatus('disconnected')
  }, [])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    } else {
      debug.warn('WebSocket', 'Not connected. Message not sent:', data)
    }
  }, [])

  // Connect on mount, cleanup on unmount
  useEffect(() => {
    connect()

    return () => {
      disconnect()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]) // Only reconnect if URL changes

  return {
    status,
    send,
    disconnect,
    reconnect: connect,
  }
}
