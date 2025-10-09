/**
 * useStatsHistory Hook - Maintains sliding window of stats data for sparklines
 *
 * FEATURES:
 * - Maintains last 40 data points per metric
 * - Handles WebSocket stats updates
 * - Automatic cleanup when component unmounts
 * - Efficient updates with React state batching
 *
 * USAGE:
 * ```tsx
 * const { addDataPoint, getHistory } = useStatsHistory('container_abc123')
 *
 * // On WebSocket message
 * addDataPoint('cpu', 45.3)
 * addDataPoint('memory', 62.1)
 *
 * // In render
 * <MiniChart data={getHistory('cpu')} color="cpu" />
 * ```
 */

import { useRef, useCallback } from 'react'
import { debug } from '@/lib/debug'

const MAX_DATA_POINTS = 40 // ~2 minutes at 3s avg interval

type MetricType = 'cpu' | 'memory' | 'network_rx' | 'network_tx'

interface StatsHistory {
  cpu: number[]
  memory: number[]
  network_rx: number[]
  network_tx: number[]
}

/**
 * Maintains a sliding window of stats history for charts
 */
export function useStatsHistory(entityId: string) {
  // Use ref to avoid unnecessary re-renders
  // Only the component that calls getHistory() will re-render
  const historyRef = useRef<StatsHistory>({
    cpu: [],
    memory: [],
    network_rx: [],
    network_tx: [],
  })

  /**
   * Add a data point to the history
   * Maintains max 40 points using sliding window
   */
  const addDataPoint = useCallback((metric: MetricType, value: number) => {
    const history = historyRef.current[metric]

    // Add new data point
    history.push(value)

    // Keep only last MAX_DATA_POINTS
    if (history.length > MAX_DATA_POINTS) {
      history.shift() // Remove oldest point
    }

    debug.log(
      'useStatsHistory',
      `Added ${metric} data point for ${entityId}: ${value} (total: ${history.length})`
    )
  }, [entityId])

  /**
   * Get the complete history for a metric
   * Returns a copy to prevent external mutations
   */
  const getHistory = useCallback((metric: MetricType): number[] => {
    return [...historyRef.current[metric]]
  }, [])

  /**
   * Get the latest value for a metric
   */
  const getLatest = useCallback((metric: MetricType): number | null => {
    const history = historyRef.current[metric]
    const latest = history.length > 0 ? history[history.length - 1] : undefined
    return latest !== undefined ? latest : null
  }, [])

  /**
   * Clear all history (useful when entity is removed)
   */
  const clearHistory = useCallback(() => {
    historyRef.current = {
      cpu: [],
      memory: [],
      network_rx: [],
      network_tx: [],
    }
    debug.log('useStatsHistory', `Cleared history for ${entityId}`)
  }, [entityId])

  /**
   * Get stats about the history (for debugging)
   */
  const getStats = useCallback(() => {
    return {
      cpu: historyRef.current.cpu.length,
      memory: historyRef.current.memory.length,
      network_rx: historyRef.current.network_rx.length,
      network_tx: historyRef.current.network_tx.length,
    }
  }, [])

  return {
    addDataPoint,
    getHistory,
    getLatest,
    clearHistory,
    getStats,
  }
}
