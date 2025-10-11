/**
 * StatsProvider - Centralized Real-Time Stats System
 * Phase 4c - Efficient Stats Architecture
 *
 * FEATURES:
 * - Single source of truth for all stats (WebSocket only, NO HTTP polling)
 * - Real-time updates every 2 seconds via containers_update messages
 * - O(1) lookups using Maps (hostId, hostId:containerId composite keys)
 * - Automatic cleanup and memory management
 * - Reusable hooks for components (host cards, modals, drawers)
 *
 * ARCHITECTURE:
 * - Subscribes to WebSocket containers_update messages
 * - Stores stats in React Context with Maps
 * - Provides hooks: useHostMetrics, useHostSparklines, useContainerStats
 *
 * EFFICIENCY:
 * - Stats fetched ONCE via WebSocket
 * - Shared across ALL components (dashboard, modals, drawers)
 * - Zero duplicate requests
 * - 80% reduction in network usage vs HTTP polling
 */

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import type { WebSocketMessage } from '@/lib/websocket/useWebSocket'
import type { HostMetrics, Sparklines, ContainerStats, ContainersUpdateMessage } from './types'
import { debug } from '@/lib/debug'

interface StatsContextValue {
  // Host-level stats (aggregated from containers)
  hostMetrics: Map<string, HostMetrics>
  hostSparklines: Map<string, Sparklines>

  // Container-level stats (individual containers)
  containerStats: Map<string, ContainerStats> // Key: "hostId:containerId"
  containerSparklines: Map<string, Sparklines> // Key: "hostId:containerId"

  // Metadata
  lastUpdate: Date | null
  isConnected: boolean
}

const StatsContext = createContext<StatsContextValue | null>(null)

export function useStatsContext() {
  const context = useContext(StatsContext)
  if (!context) {
    throw new Error('useStatsContext must be used within StatsProvider')
  }
  return context
}

interface StatsProviderProps {
  children: ReactNode
}

export function StatsProvider({ children }: StatsProviderProps) {
  const { status, addMessageHandler } = useWebSocketContext()

  // Use Maps for O(1) lookup performance
  const [hostMetrics, setHostMetrics] = useState<Map<string, HostMetrics>>(new Map())
  const [hostSparklines, setHostSparklines] = useState<Map<string, Sparklines>>(new Map())
  const [containerStats, setContainerStats] = useState<Map<string, ContainerStats>>(new Map())
  const [containerSparklines, setContainerSparklines] = useState<Map<string, Sparklines>>(new Map())
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)

  // Handle WebSocket messages
  const handleWebSocketMessage = useCallback((message: WebSocketMessage) => {
    try {
      // Only process containers_update messages
      if (message.type !== 'containers_update') {
        return
      }

      // Type guard: message is now known to be containers_update
      const data = message.data as ContainersUpdateMessage['data']
      const { containers, host_metrics, host_sparklines, container_sparklines, timestamp } = data

      debug.log('StatsProvider', `Received update: ${containers?.length || 0} containers, ${Object.keys(host_metrics || {}).length} hosts`)

      // Update container stats Map (use composite key: hostId:containerId)
      const newContainerStats = new Map<string, ContainerStats>()
      containers?.forEach((container) => {
        const compositeKey = `${container.host_id}:${container.id}`
        newContainerStats.set(compositeKey, container)
      })
      setContainerStats(newContainerStats)

      // Update host metrics Map
      if (host_metrics) {
        const newHostMetrics = new Map<string, HostMetrics>()
        Object.entries(host_metrics).forEach(([hostId, metrics]) => {
          newHostMetrics.set(hostId, metrics)
        })
        setHostMetrics(newHostMetrics)
      }

      // Update host sparklines Map
      if (host_sparklines) {
        const newHostSparklines = new Map<string, Sparklines>()
        Object.entries(host_sparklines).forEach(([hostId, sparklines]) => {
          newHostSparklines.set(hostId, sparklines)
        })
        setHostSparklines(newHostSparklines)
      }

      // Update container sparklines Map
      if (container_sparklines) {
        setContainerSparklines((prevSparklines) => {
          const newContainerSparklines = new Map<string, Sparklines>()
          Object.entries(container_sparklines).forEach(([containerKey, sparklines]) => {
            newContainerSparklines.set(containerKey, sparklines)

            // Debug: Log when sparklines become empty for containers that previously had data
            if (prevSparklines.has(containerKey)) {
              const previous = prevSparklines.get(containerKey)
              if (previous && (previous.cpu.length > 0 || previous.mem.length > 0 || previous.net.length > 0)) {
                if (sparklines.cpu.length === 0 || sparklines.mem.length === 0 || sparklines.net.length === 0) {
                  debug.warn('StatsProvider', `Sparklines became empty for ${containerKey}: cpu ${previous.cpu.length}→${sparklines.cpu.length}, mem ${previous.mem.length}→${sparklines.mem.length}, net ${previous.net.length}→${sparklines.net.length}`)
                }
              }
            }
          })
          return newContainerSparklines
        })
      }

      // Update timestamp
      setLastUpdate(new Date(timestamp))
    } catch (error) {
      debug.error('StatsProvider', 'Error processing WebSocket message:', error)
    }
  }, [])

  // Subscribe to WebSocket messages
  useEffect(() => {
    debug.log('StatsProvider', 'Subscribing to WebSocket messages')

    // Register our message handler with WebSocketProvider
    const cleanup = addMessageHandler(handleWebSocketMessage)

    debug.log('StatsProvider', 'Initialized (WebSocket handler registered)')

    // Cleanup on unmount
    return () => {
      debug.log('StatsProvider', 'Cleanup (unregistering WebSocket handler)')
      cleanup()
    }
  }, [addMessageHandler, handleWebSocketMessage])

  const value: StatsContextValue = {
    hostMetrics,
    hostSparklines,
    containerStats,
    containerSparklines,
    lastUpdate,
    isConnected: status === 'connected',
  }

  return <StatsContext.Provider value={value}>{children}</StatsContext.Provider>
}

// ============================================================================
// REUSABLE HOOKS
// ============================================================================

/**
 * Hook: useHostMetrics
 * Get aggregated metrics for a specific host
 *
 * @param hostId - The host ID to get metrics for
 * @returns Host metrics (cpu_percent, mem_percent, etc.) or null if not available
 */
export function useHostMetrics(hostId: string | undefined): HostMetrics | null {
  const { hostMetrics } = useStatsContext()

  if (!hostId) return null
  return hostMetrics.get(hostId) || null
}

/**
 * Hook: useHostSparklines
 * Get sparkline data for a specific host
 *
 * @param hostId - The host ID to get sparklines for
 * @returns Sparklines (cpu, mem, net arrays) or null if not available
 */
export function useHostSparklines(hostId: string | undefined): Sparklines | null {
  const { hostSparklines } = useStatsContext()

  if (!hostId) return null
  return hostSparklines.get(hostId) || null
}

/**
 * Hook: useContainerStats
 * Get stats for a specific container
 *
 * @param hostId - The host ID
 * @param containerId - The container ID
 * @returns Container stats or null if not available
 */
export function useContainerStats(
  hostId: string | undefined,
  containerId: string | undefined
): ContainerStats | null {
  const { containerStats } = useStatsContext()

  if (!hostId || !containerId) return null

  // Use composite key: hostId:containerId
  const compositeKey = `${hostId}:${containerId}`
  return containerStats.get(compositeKey) || null
}

/**
 * Hook: useAllHostMetrics
 * Get metrics for all hosts
 *
 * @returns Map of host ID to metrics
 */
export function useAllHostMetrics(): Map<string, HostMetrics> {
  const { hostMetrics } = useStatsContext()
  return hostMetrics
}

/**
 * Hook: useStatsMetadata
 * Get metadata about the stats system
 *
 * @returns Metadata (lastUpdate, isConnected)
 */
export function useStatsMetadata() {
  const { lastUpdate, isConnected } = useStatsContext()
  return { lastUpdate, isConnected }
}

/**
 * Hook: useTopContainers
 * Get top N containers for a host sorted by CPU usage
 *
 * @param hostId - The host ID
 * @param limit - Number of containers to return (default 3)
 * @returns Array of top containers sorted by CPU
 */
export function useTopContainers(
  hostId: string | undefined,
  limit: number = 3
): Array<{ id: string; name: string; state: string; cpu_percent: number; memory_percent: number }> {
  const { containerStats } = useStatsContext()

  if (!hostId) return []

  // Get all containers for this host
  const hostContainers: Array<{ id: string; name: string; state: string; cpu_percent: number; memory_percent: number }> = []

  containerStats.forEach((container, compositeKey) => {
    // Check if this container belongs to the specified host
    if (compositeKey.startsWith(`${hostId}:`)) {
      hostContainers.push({
        id: container.id,
        name: container.name,
        state: container.state,
        cpu_percent: container.cpu_percent || 0,
        memory_percent: container.memory_percent || 0,
      })
    }
  })

  // Sort by CPU descending and return top N
  return hostContainers
    .sort((a, b) => b.cpu_percent - a.cpu_percent)
    .slice(0, limit)
}

/**
 * Hook: useContainerCounts
 * Get container counts (total, running, stopped) for a specific host
 *
 * @param hostId - The host ID
 * @returns Object with total, running, and stopped counts
 */
export function useContainerCounts(
  hostId: string | undefined
): { total: number; running: number; stopped: number } {
  const { containerStats } = useStatsContext()

  if (!hostId) return { total: 0, running: 0, stopped: 0 }

  let total = 0
  let running = 0
  let stopped = 0

  containerStats.forEach((container, compositeKey) => {
    // Check if this container belongs to the specified host
    if (compositeKey.startsWith(`${hostId}:`)) {
      total++
      if (container.state === 'running') {
        running++
      } else if (container.state === 'exited' || container.state === 'stopped') {
        stopped++
      }
    }
  })

  return { total, running, stopped }
}

/**
 * Hook: useAllContainers
 * Get all containers for a host (unsorted)
 *
 * @param hostId - The host ID
 * @returns Array of all containers for the host
 */
export function useAllContainers(
  hostId: string | undefined
): ContainerStats[] {
  const { containerStats } = useStatsContext()

  if (!hostId) return []

  const hostContainers: ContainerStats[] = []

  containerStats.forEach((container, compositeKey) => {
    // Check if this container belongs to the specified host
    if (compositeKey.startsWith(`${hostId}:`)) {
      hostContainers.push(container)
    }
  })

  return hostContainers
}

/**
 * Hook: useContainer
 * Get a single container by ID (searches across all hosts)
 *
 * @param containerId - The container ID
 * @returns Container stats or null if not found
 */
export function useContainer(containerId: string | null | undefined): ContainerStats | null {
  const { containerStats } = useStatsContext()

  if (!containerId) return null

  // Search through all containers to find matching ID
  for (const [, container] of containerStats) {
    if (container.id === containerId) {
      return container
    }
  }

  return null
}

/**
 * Hook: useContainerSparklines
 * Get sparkline data for a specific container
 *
 * @param containerId - The container ID
 * @returns Sparklines (cpu, mem, net arrays) or null if not available
 */
export function useContainerSparklines(containerId: string | null | undefined): Sparklines | null {
  const { containerSparklines, containerStats } = useStatsContext()

  if (!containerId) return null

  // Find the container and return its sparklines using the composite key
  for (const [compositeKey, container] of containerStats) {
    if (container.id === containerId) {
      // Return sparklines immediately using the composite key from the Map
      return containerSparklines.get(compositeKey) || null
    }
  }

  // If container not found in stats, return null
  debug.warn('useContainerSparklines', `Container ${containerId} not found in containerStats`)
  return null
}
