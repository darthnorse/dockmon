import { useState, useEffect, useCallback, useRef } from 'react'
import { X, CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react'
import { apiClient } from '@/lib/api/client'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import { useQueryClient } from '@tanstack/react-query'
import { debug } from '@/lib/debug'
import { useTimeFormat } from '@/lib/hooks/useUserPreferences'
import { formatTime } from '@/lib/utils/timeFormat'
import type { WebSocketMessage } from '@/lib/websocket/useWebSocket'

interface BatchJobStatus {
  id: string
  scope: string
  action: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  total_items: number
  completed_items: number
  success_items: number
  error_items: number
  skipped_items: number
  created_at: string
  started_at?: string
  completed_at?: string
  items: BatchJobItem[]
}

interface BatchJobItem {
  id: number
  container_id: string
  container_name: string
  host_id: string
  host_name?: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'skipped'
  message?: string
  started_at?: string
  completed_at?: string
}

interface BatchJobPanelProps {
  jobId: string | null
  isVisible: boolean
  onClose: () => void
  onJobComplete: () => void
  bulkActionBarOpen?: boolean
}

export function BatchJobPanel({ jobId, isVisible, onClose, onJobComplete, bulkActionBarOpen = false }: BatchJobPanelProps) {
  const { timeFormat } = useTimeFormat()
  const [job, setJob] = useState<BatchJobStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { addMessageHandler } = useWebSocketContext()
  const queryClient = useQueryClient()
  const autoCloseTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  // Fetch initial job status
  useEffect(() => {
    if (!jobId) {
      setJob(null)
      return
    }

    let cancelled = false

    const fetchJob = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await apiClient.get<BatchJobStatus>(`/batch/${jobId}`)
        if (!cancelled) {
          setJob(data)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to fetch job status')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    fetchJob()

    return () => {
      cancelled = true
    }
  }, [jobId])

  // Handle WebSocket messages
  const handleMessage = useCallback((message: WebSocketMessage) => {
    if (!jobId) return

    // Handle batch job updates
    if (message.type === 'batch_job_update' && message.data && typeof message.data === 'object') {
      const data = message.data as Record<string, unknown>
      if (data.job_id === jobId) {
        const newStatus = data.status as string

        setJob(prev => {
          const prevStatus = prev?.status
          const updatedJob = prev ? { ...prev, ...data } : null

          // Invalidate queries and cleanup when job finishes (completed or failed)
          // Only trigger on actual state transition from in-progress to finished
          // This prevents premature cleanup when WebSocket 'completed' arrives before initial fetch
          const wasInProgress = prevStatus === 'queued' || prevStatus === 'running'
          const isNowFinished = newStatus === 'completed' || newStatus === 'failed'

          if (wasInProgress && isNowFinished) {
            const action = prev?.action || (data.action as string)

            // Invalidate cache regardless of success/failure (shows current state)
            queryClient.invalidateQueries({ queryKey: ['containers'] })

            // For delete-images action, invalidate host-images queries
            if (action === 'delete-images') {
              const items = (prev?.items || data.items) as BatchJobItem[] | undefined
              if (items && items.length > 0) {
                // Get unique host IDs from items
                const hostIds = new Set(items.map((item: BatchJobItem) => item.host_id))
                hostIds.forEach((hostId) => {
                  queryClient.invalidateQueries({ queryKey: ['host-images', hostId] })
                })
              }
            }

            // For auto-update and check-updates actions, also invalidate update-status queries
            // Force refetch even with staleTime: Infinity
            if (action === 'set-auto-update' || action === 'check-updates') {
              // Get affected containers from job items
              const items = (prev?.items || data.items) as BatchJobItem[] | undefined

              if (items && items.length > 0) {
                // Invalidate only the specific containers that were affected
                items.forEach((item: BatchJobItem) => {
                  queryClient.invalidateQueries({
                    queryKey: ['container-update-status', item.host_id, item.container_id],
                    refetchType: 'active'
                  })
                })
              } else {
                // Fallback: invalidate all if we don't have item details
                queryClient.invalidateQueries({
                  queryKey: ['container-update-status'],
                  refetchType: 'active'
                })
              }

              // Also invalidate updates-summary so filters update immediately (fixes #115)
              queryClient.invalidateQueries({ queryKey: ['updates-summary'] })
            }

            debug.log('BatchJobPanel', `Job ${jobId} finished (${newStatus}), invalidated queries for action: ${action}`)

            // Clear any existing timeout before setting new one
            if (autoCloseTimeoutRef.current) {
              clearTimeout(autoCloseTimeoutRef.current)
            }

            // Auto-close panel 3 seconds after completion
            autoCloseTimeoutRef.current = setTimeout(() => {
              onJobComplete()
            }, 3000)
          }

          return updatedJob
        })
      }
    }

    // Handle individual item updates
    if (message.type === 'batch_item_update' && message.data && typeof message.data === 'object') {
      const data = message.data as Record<string, unknown>
      if (data.job_id === jobId) {
        setJob(prev => {
          if (!prev) return null

          const items = prev.items.map(item =>
            item.id === data.item_id
              ? { ...item, ...data }
              : item
          )

          return { ...prev, items }
        })
      }
    }
  }, [jobId, queryClient, onJobComplete])

  // Subscribe to WebSocket messages
  useEffect(() => {
    const unsubscribe = addMessageHandler(handleMessage)
    return unsubscribe
  }, [addMessageHandler, handleMessage])

  // Cleanup timeout on unmount or jobId change
  useEffect(() => {
    return () => {
      if (autoCloseTimeoutRef.current) {
        clearTimeout(autoCloseTimeoutRef.current)
        autoCloseTimeoutRef.current = null
      }
    }
  }, [jobId])

  // Handle manual close - clear timeout and cleanup
  const handleClose = useCallback(() => {
    if (autoCloseTimeoutRef.current) {
      clearTimeout(autoCloseTimeoutRef.current)
      autoCloseTimeoutRef.current = null
    }
    onClose()
  }, [onClose])

  // Only unmount if no job is being tracked
  if (!jobId) return null

  // If job exists but panel is hidden, keep mounted but don't render anything
  // This ensures WebSocket handler stays alive to receive job completion
  if (!isVisible) {
    return null
  }

  const progressPercent = job && job.total_items > 0
    ? Math.round((job.completed_items / job.total_items) * 100)
    : 0

  const actionLabels: Record<string, string> = {
    start: 'Starting',
    stop: 'Stopping',
    restart: 'Restarting',
    'delete-images': 'Deleting images',
    'delete-containers': 'Deleting containers',
    'add-tags': 'Adding tags',
    'remove-tags': 'Removing tags',
    'set-auto-restart': 'Configuring auto-restart',
    'set-auto-update': 'Configuring auto-update',
    'set-desired-state': 'Setting desired state',
    'check-updates': 'Checking for updates',
    'update-containers': 'Updating containers',
  }

  const statusIcons = {
    queued: <Clock className="h-4 w-4 text-muted-foreground" />,
    running: <Loader2 className="h-4 w-4 text-info animate-spin" />,
    completed: <CheckCircle className="h-4 w-4 text-success" />,
    failed: <XCircle className="h-4 w-4 text-destructive" />,
    skipped: <Clock className="h-4 w-4 text-warning" />,
  }

  return (
    <div
      className={`fixed right-0 w-96 bg-surface-1 border-l border-t border-border shadow-xl flex flex-col max-h-[70vh] z-40 transition-all duration-200 ${
        bulkActionBarOpen ? 'bottom-[280px]' : 'bottom-0'
      }`}
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Batch Operation
          </h3>
          <p className="text-xs text-muted-foreground">
            {job ? actionLabels[job.action] || job.action : 'Loading...'} {job?.total_items || 0} containers
          </p>
        </div>
        <button
          onClick={handleClose}
          className="p-1 hover:bg-surface-2 rounded transition-colors"
          title="Close"
        >
          <X className="h-4 w-4 text-muted-foreground" />
        </button>
      </div>

      {/* Progress Bar */}
      {job && (
        <div className="px-4 py-3 border-b border-border">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="text-muted-foreground">
              {job.completed_items} of {job.total_items}
            </span>
            <span className="font-medium text-foreground">
              {progressPercent}%
            </span>
          </div>
          <div className="w-full bg-surface-2 rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all duration-300 ${
                job.status === 'failed'
                  ? 'bg-destructive'
                  : job.status === 'completed'
                  ? 'bg-success'
                  : 'bg-primary'
              }`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <div className="flex items-center gap-4 mt-2 text-xs">
            <span className="text-success">
              ✓ {job.success_items} success
            </span>
            {job.error_items > 0 && (
              <span className="text-destructive">
                ✗ {job.error_items} failed
              </span>
            )}
            {job.skipped_items > 0 && (
              <span className="text-warning">
                ⊘ {job.skipped_items} skipped
              </span>
            )}
          </div>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="px-4 py-3 bg-destructive/10 border-b border-border">
          <div className="flex items-start gap-2">
            <XCircle className="h-4 w-4 text-destructive mt-0.5 flex-shrink-0" />
            <div className="flex-1">
              <p className="text-sm text-destructive font-medium">Failed to load batch job</p>
              <p className="text-xs text-destructive/80 mt-1">{error}</p>
              <button
                onClick={() => {
                  setError(null)
                  setLoading(true)
                  apiClient.get<BatchJobStatus>(`/batch/${jobId}`)
                    .then(data => setJob(data))
                    .catch(err => {
                      const errorMsg = err instanceof Error ? err.message : 'Failed to fetch job status'
                      debug.error('BatchJobPanel', 'Batch job retry failed:', err)
                      setError(errorMsg)
                    })
                    .finally(() => setLoading(false))
                }}
                className="mt-2 text-xs text-primary hover:text-primary/80 font-medium"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="flex-1 flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 text-muted-foreground animate-spin" />
        </div>
      )}

      {/* Item List */}
      {job && !loading && (
        <div className="flex-1 overflow-y-auto">
          <div className="divide-y divide-border">
            {job.items.map((item) => (
              <div
                key={item.id}
                className="px-4 py-3 hover:bg-surface-2 transition-colors"
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5">
                    {statusIcons[item.status]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">
                      {item.container_name}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {item.host_name || 'localhost'}
                    </div>
                    {item.message && (
                      <div className={`text-xs mt-1 ${
                        item.status === 'failed'
                          ? 'text-destructive'
                          : item.status === 'skipped'
                          ? 'text-warning'
                          : 'text-muted-foreground'
                      }`}>
                        {item.message}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Footer - Status Summary */}
      {job && job.status === 'completed' && (
        <div className="px-4 py-3 border-t border-border bg-surface-2">
          <p className="text-xs text-muted-foreground text-center">
            {job.completed_at ? (
              <>
                Completed at {formatTime(job.completed_at, timeFormat, true)}
              </>
            ) : (
              'Completed'
            )}
          </p>
        </div>
      )}
    </div>
  )
}
