/**
 * Shared Layer Progress Display Component
 *
 * Beautiful layer-by-layer progress tracking used by:
 * - Container Updates (ContainerUpdatesTab)
 * - Deployments (DeploymentsPage)
 *
 * Displays:
 * - Overall progress bar with summary
 * - Layer-by-layer download details
 * - Download speeds (MB/s)
 * - Collapsible layer details
 * - Real-time updates via WebSocket
 */

import { useState, useEffect, useCallback } from 'react'
import { cn } from '@/lib/utils'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'

interface LayerProgress {
  id: string
  status: string  // "Pulling fs layer" | "Downloading" | "Verifying Checksum" | "Download complete" | "Extracting" | "Pull complete" | "Already exists"
  current: number  // Bytes
  total: number    // Bytes
  percent: number  // 0-100
}

interface LayerProgressData {
  overall_progress: number
  layers: LayerProgress[]
  total_layers: number
  remaining_layers: number
  summary: string
  speed_mbps?: number
}

interface SimpleProgress {
  stage: string
  progress: number
  message: string
}

interface LayerProgressDisplayProps {
  hostId: string
  entityId: string  // container_id or deployment_id
  eventType: 'container_update_layer_progress' | 'deployment_layer_progress'
  simpleProgressEventType?: 'container_update_progress' | 'deployment_progress'
  initialProgress?: number
  initialMessage?: string
  disableAutoCollapse?: boolean  // Disable auto-collapse for multi-service deployments
}

// Helper function to format bytes
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

/**
 * Shared layer progress display component
 * Extracted from ContainerUpdatesTab.tsx (the design you love!)
 */
export function LayerProgressDisplay({
  hostId,
  entityId,
  eventType,
  simpleProgressEventType,
  initialProgress = 0,
  initialMessage = 'Starting...',
  disableAutoCollapse = false,
}: LayerProgressDisplayProps) {
  const { addMessageHandler } = useWebSocketContext()

  // Simple progress state (fallback when no layer data)
  const [updateProgress, setUpdateProgress] = useState<SimpleProgress | null>({
    stage: 'starting',
    progress: initialProgress,
    message: initialMessage,
  })

  // Layer-by-layer progress state (detailed view)
  const [layerProgress, setLayerProgress] = useState<LayerProgressData | null>(null)
  const [layerDetailsExpanded, setLayerDetailsExpanded] = useState(true)  // Default expanded

  // Store completion timeout IDs for cleanup (prevents memory leak)
  const [completionTimeoutId, setCompletionTimeoutId] = useState<NodeJS.Timeout | null>(null)
  const [collapseTimeoutId, setCollapseTimeoutId] = useState<NodeJS.Timeout | null>(null)

  // Listen for WebSocket progress messages
  const handleProgressMessage = useCallback(
    (message: any) => {
      // Support both message structures:
      // 1. Container updates: message.data.host_id, message.data.entity_id
      // 2. Deployments: message.host_id, message.deployment_id
      const msgHostId = message.data?.host_id || message.host_id
      const msgEntityId = message.data?.entity_id || message.deployment_id

      if (msgHostId === hostId && msgEntityId === entityId) {
        // Handle simple progress (container updates use message.data, deployments use message.progress)
        if (simpleProgressEventType && message.type === simpleProgressEventType) {
          // Deployment progress structure
          const progress = message.progress || message.data
          setUpdateProgress({
            stage: progress?.stage || message.data?.stage,
            progress: progress?.overall_percent ?? message.data?.progress,
            message: progress?.stage || message.data?.message || 'Processing...',
          })

          // Clear progress when update completes
          const stage = progress?.stage || message.data?.stage
          if (stage === 'completed' || message.status === 'running') {
            // Clear any existing timeout first
            if (completionTimeoutId) {
              clearTimeout(completionTimeoutId)
            }

            // Set new timeout and store ID for cleanup
            const timeoutId = setTimeout(() => {
              setUpdateProgress(null)
              setLayerProgress(null)
              setCompletionTimeoutId(null)
            }, 3000)
            setCompletionTimeoutId(timeoutId)
          }
        }

        // Handle NEW layer progress (enhanced view)
        if (message.type === eventType) {
          // Build summary with speed appended if not already included
          // Docker SDK includes speed in summary, agent sends it separately
          let summary = message.data.summary || ''
          const speedMbps = message.data.speed_mbps
          if (speedMbps && speedMbps > 0 && !summary.includes('MB/s')) {
            summary = `${summary} @ ${speedMbps.toFixed(1)} MB/s`
          }

          setLayerProgress({
            overall_progress: message.data.overall_progress,
            layers: message.data.layers,
            total_layers: message.data.total_layers,
            remaining_layers: message.data.remaining_layers,
            summary: summary,
            speed_mbps: message.data.speed_mbps,
          })
        }
      }
    },
    [hostId, entityId, eventType, simpleProgressEventType, completionTimeoutId]
  )

  useEffect(() => {
    const cleanup = addMessageHandler(handleProgressMessage)

    // Return combined cleanup function
    return () => {
      cleanup()

      // Clear timeouts if component unmounts (prevents memory leak)
      if (completionTimeoutId) {
        clearTimeout(completionTimeoutId)
      }
      if (collapseTimeoutId) {
        clearTimeout(collapseTimeoutId)
      }
    }
  }, [addMessageHandler, handleProgressMessage, completionTimeoutId, collapseTimeoutId])

  // Auto-collapse layer details 2 seconds after reaching 100% (unless disabled)
  useEffect(() => {
    if (disableAutoCollapse) return

    if (layerProgress && layerProgress.overall_progress === 100 && layerDetailsExpanded) {
      // Clear any existing collapse timeout
      if (collapseTimeoutId) {
        clearTimeout(collapseTimeoutId)
      }

      // Set new timeout to collapse after 2 seconds
      const timeoutId = setTimeout(() => {
        setLayerDetailsExpanded(false)
        setCollapseTimeoutId(null)
      }, 2000)

      setCollapseTimeoutId(timeoutId)
    }
  }, [layerProgress?.overall_progress, layerDetailsExpanded, collapseTimeoutId, disableAutoCollapse])

  // Don't render if no progress data
  if (!updateProgress && !layerProgress) {
    return null
  }

  // Determine if we have detailed layer progress or just simple progress
  // Docker SDK deployments/updates have layerProgress, agent deployments don't
  const hasDetailedProgress = layerProgress !== null

  return (
    <div className="space-y-3 rounded-lg border border-blue-500/50 bg-blue-500/10 p-4" data-testid="layer-progress-display">
      {/* Overall progress bar */}
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium text-blue-400">
          {hasDetailedProgress
            ? layerProgress.summary
            : updateProgress?.message || 'Deploying, please wait...'}
        </span>
        <span className="text-blue-400">
          {hasDetailedProgress
            ? `${layerProgress.overall_progress}%`
            : updateProgress?.progress !== undefined
              ? `${updateProgress.progress}%`
              : ''}
        </span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-blue-950">
        {hasDetailedProgress ? (
          <div
            className="h-full bg-blue-500 transition-all duration-500 ease-out"
            style={{ width: `${layerProgress.overall_progress}%` }}
          />
        ) : updateProgress?.progress !== undefined ? (
          /* Simple progress bar when we have progress percentage but no layer details */
          <div
            className="h-full bg-blue-500 transition-all duration-500 ease-out"
            style={{ width: `${updateProgress.progress}%` }}
          />
        ) : (
          /* Indeterminate animated bar when no progress data at all */
          <div className="h-full w-full bg-gradient-to-r from-blue-500/30 via-blue-500 to-blue-500/30 animate-pulse" />
        )}
      </div>

      {/* Collapse/Expand toggle (optional polish) */}
      {layerProgress && layerProgress.layers.length > 0 && (
        <button
          onClick={() => setLayerDetailsExpanded(!layerDetailsExpanded)}
          className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
        >
          {layerDetailsExpanded ? '▼ Hide layer details' : '▶ Show layer details'}
        </button>
      )}

      {/* Layer-by-layer progress (THE BEAUTIFUL PART!) */}
      {layerDetailsExpanded && layerProgress && layerProgress.layers.length > 0 && (
        <div className="mt-4 space-y-1.5 max-h-48 overflow-y-auto text-xs font-mono" data-testid="layer-progress">
          {layerProgress.layers.slice(0, 15).map((layer) => {
            // Determine status color with CSS transitions
            let statusColor = 'text-muted-foreground'
            if (layer.status === 'Pull complete') statusColor = 'text-green-400'
            else if (layer.status === 'Download complete') statusColor = 'text-green-400'
            else if (layer.status === 'Already exists') statusColor = 'text-green-400/60'
            else if (layer.status === 'Downloading') statusColor = 'text-blue-400'
            else if (layer.status === 'Extracting') statusColor = 'text-yellow-400'
            else if (layer.status === 'Verifying Checksum') statusColor = 'text-purple-400'

            return (
              <div
                key={layer.id}
                className="flex items-center gap-2 py-0.5 transition-colors duration-300"
              >
                <span className="text-muted-foreground/60 w-24 truncate">
                  {layer.id}
                </span>
                <span className={cn("flex-1 transition-colors duration-300", statusColor)}>
                  {layer.status}
                </span>
                {layer.total > 0 && (
                  <span className="text-muted-foreground/80 text-right w-32">
                    {layer.percent}% of {formatBytes(layer.total)}
                  </span>
                )}
              </div>
            )
          })}

          {layerProgress.layers.length > 15 && (
            <div className="text-muted-foreground/60 text-center pt-2 border-t border-muted-foreground/10">
              ... and {layerProgress.remaining_layers > 0
                ? layerProgress.remaining_layers + (layerProgress.layers.length - 15)
                : layerProgress.layers.length - 15} more layers
            </div>
          )}
        </div>
      )}
    </div>
  )
}
