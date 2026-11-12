import { useState, useEffect, useCallback, useRef } from 'react'
import { X, CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react'
import { apiClient, ApiError } from '@/lib/api/client'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import { useQueryClient } from '@tanstack/react-query'
import { debug } from '@/lib/debug'
import { useTimeFormat } from '@/lib/hooks/useUserPreferences'
import { formatTime } from '@/lib/utils/timeFormat'
import { useAuth } from '@/features/auth/AuthContext'
import type { WebSocketMessage } from '@/lib/websocket/useWebSocket'

interface BatchJobStatus {
  id: string
  scope: string
  action: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'partial'
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
  status: 'queued' | 'running' | 'success' | 'error' | 'skipped'
  message?: string
  started_at?: string
  completed_at?: string
}

// Covers a reverse proxy or DockMon restart (e.g. updating Caddy in this very batch).
const CONNECTION_RETRY_DELAYS_MS = [1000, 2000, 4000]
// What a reachable proxy returns while the DockMon backend behind it restarts.
const GATEWAY_STATUSES = new Set([502, 503, 504])

const isInProgress = (status?: string) => status === 'queued' || status === 'running'
const isFinished = (status?: string) => status === 'completed' || status === 'failed' || status === 'partial'
const isTransient = (err: unknown) => !(err instanceof ApiError) || GATEWAY_STATUSES.has(err.status)

// A snapshot fetched before live updates that were applied meanwhile must not roll them back.
const isBehind = (snapshot: BatchJobStatus, current: BatchJobStatus) =>
  (isFinished(current.status) && !isFinished(snapshot.status)) || snapshot.completed_items < current.completed_items

interface BatchJobPanelProps {
  jobId: string | null
  isVisible: boolean
  onClose: () => void
  onJobComplete: () => void
  bulkActionBarOpen?: boolean
}

export function BatchJobPanel({ jobId, isVisible, onClose, onJobComplete, bulkActionBarOpen = false }: BatchJobPanelProps) {
  const { hasCapability } = useAuth()
  const canViewBatch = hasCapability('batch.view')
  const { timeFormat } = useTimeFormat()
  const [job, setJob] = useState<BatchJobStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reconnecting, setReconnecting] = useState(false)
  const { addMessageHandler, status: wsStatus } = useWebSocketContext()
  const queryClient = useQueryClient()
  const autoCloseTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  // Source of truth for handlers and async loads; React state only drives rendering.
  const jobRef = useRef<BatchJobStatus | null>(null)
  const loadGenerationRef = useRef(0)
  const loadInFlightRef = useRef(false)
  const refreshQueuedRef = useRef(false)

  const commitJob = useCallback((next: BatchJobStatus | null) => {
    jobRef.current = next
    setJob(next)
  }, [])

  const finishJob = useCallback((action: string, items: BatchJobItem[] | undefined) => {
    // Invalidate cache regardless of success/failure (shows current state)
    void queryClient.invalidateQueries({ queryKey: ['containers'] })

    if (action === 'delete-images' && items && items.length > 0) {
      const hostIds = new Set(items.map((item) => item.host_id))
      hostIds.forEach((hostId) => {
        void queryClient.invalidateQueries({ queryKey: ['host-images', hostId] })
      })
    }

    // Force refetch even with staleTime: Infinity
    if (action === 'set-auto-update' || action === 'check-updates') {
      if (items && items.length > 0) {
        items.forEach((item) => {
          void queryClient.invalidateQueries({
            queryKey: ['container-update-status', item.host_id, item.container_id],
            refetchType: 'active'
          })
        })
      } else {
        void queryClient.invalidateQueries({
          queryKey: ['container-update-status'],
          refetchType: 'active'
        })
      }

      // Also invalidate updates-summary so filters update immediately
      void queryClient.invalidateQueries({ queryKey: ['updates-summary'] })
    }

    debug.log('BatchJobPanel', `Job ${jobId} finished, invalidated queries for action: ${action}`)

    if (autoCloseTimeoutRef.current) {
      clearTimeout(autoCloseTimeoutRef.current)
    }
    autoCloseTimeoutRef.current = setTimeout(() => {
      onJobComplete()
    }, 3000)
  }, [jobId, queryClient, onJobComplete])
  const finishJobRef = useRef(finishJob)
  finishJobRef.current = finishJob

  /**
   * Fetch the job, retrying transient failures (no response, or a gateway error
   * while DockMon restarts) before surfacing them; other HTTP errors show at once.
   * `refresh` marks a catch-up fetch, which completes the job if it finished unseen.
   */
  const loadJob = useCallback(async (refresh: boolean): Promise<void> => {
    if (!jobId || !canViewBatch) return
    const generation = ++loadGenerationRef.current
    loadInFlightRef.current = true
    refreshQueuedRef.current = false
    if (!refresh || !jobRef.current) setLoading(true)
    setError(null)
    setReconnecting(false)

    for (let attempt = 0; ; attempt++) {
      try {
        const data = await apiClient.get<BatchJobStatus>(`/batch/${jobId}`)
        if (generation !== loadGenerationRef.current) return
        loadInFlightRef.current = false
        setReconnecting(false)
        setLoading(false)
        const current = jobRef.current
        if (!current || !isBehind(data, current)) {
          commitJob(data)
          if (refresh && !isFinished(current?.status) && isFinished(data.status)) {
            finishJobRef.current(data.action, data.items)
          }
        }
        if (refreshQueuedRef.current) void loadJob(true)
        return
      } catch (err) {
        if (generation !== loadGenerationRef.current) return
        const delay = CONNECTION_RETRY_DELAYS_MS[attempt]
        if (isTransient(err) && delay !== undefined) {
          setReconnecting(true)
          await new Promise((resolve) => setTimeout(resolve, delay))
          if (generation !== loadGenerationRef.current) return
          continue
        }
        loadInFlightRef.current = false
        setReconnecting(false)
        setLoading(false)
        setError(err instanceof Error ? err.message : 'Failed to fetch job status')
        return
      }
    }
  }, [jobId, canViewBatch, commitJob])

  useEffect(() => {
    commitJob(null)
    setError(null)
    setReconnecting(false)
    loadInFlightRef.current = false
    refreshQueuedRef.current = false
    if (!jobId || !canViewBatch) return
    void loadJob(false)
    const generations = loadGenerationRef
    return () => {
      generations.current++
    }
  }, [jobId, canViewBatch, loadJob, commitJob])

  // Messages sent while the live connection was down are lost; catch up on reconnect.
  const prevWsStatusRef = useRef(wsStatus)
  useEffect(() => {
    const previous = prevWsStatusRef.current
    prevWsStatusRef.current = wsStatus
    if (wsStatus !== 'connected' || previous === 'connected') return
    const current = jobRef.current
    if (!current || isInProgress(current.status)) void loadJob(true)
  }, [wsStatus, loadJob])

  const handleMessage = useCallback((message: WebSocketMessage) => {
    if (!jobId || !canViewBatch) return
    if (message.type !== 'batch_job_update' && message.type !== 'batch_item_update') return
    if (!message.data || typeof message.data !== 'object') return
    const data = message.data as Record<string, unknown>
    if (data.job_id !== jobId) return

    setError(null)
    const prev = jobRef.current
    if (!prev) {
      // The job isn't loaded yet: fetch it rather than patch nothing, one request at a time.
      if (loadInFlightRef.current) {
        refreshQueuedRef.current = true
      } else {
        void loadJob(true)
      }
      return
    }

    if (message.type === 'batch_job_update') {
      commitJob({ ...prev, ...data } as BatchJobStatus)
      // A job loaded already finished is not finished again.
      if (isInProgress(prev.status) && isFinished(data.status as string)) {
        finishJob(prev.action, prev.items)
      }
      return
    }

    const items = prev.items.map((item) => (item.id === data.item_id ? { ...item, ...data } : item))
    commitJob({ ...prev, items })
  }, [jobId, canViewBatch, finishJob, loadJob, commitJob])

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

  if (!canViewBatch) {
    if (!isVisible) return null
    return (
      <div
        className={`fixed right-0 w-96 bg-surface-1 border-l border-t border-border shadow-xl flex flex-col z-40 transition-all duration-200 ${
          bulkActionBarOpen ? 'bottom-[280px]' : 'bottom-0'
        }`}
      >
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">Batch Operation</h3>
          <button onClick={handleClose} className="p-1 hover:bg-surface-2 rounded transition-colors" title="Close">
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          You do not have permission to view batch job status.
        </div>
      </div>
    )
  }

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
    success: <CheckCircle className="h-4 w-4 text-success" />,
    error: <XCircle className="h-4 w-4 text-destructive" />,
    skipped: <Clock className="h-4 w-4 text-warning" />,
  }

  const progressBarColors: Record<BatchJobStatus['status'], string> = {
    queued: 'bg-primary',
    running: 'bg-primary',
    completed: 'bg-success',
    partial: 'bg-warning',
    failed: 'bg-destructive',
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
              className={`h-2 rounded-full transition-all duration-300 ${progressBarColors[job.status]}`}
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

      {reconnecting && (
        <div className="px-4 py-2 border-b border-border text-xs text-muted-foreground flex items-center gap-2">
          <Loader2 className="h-3 w-3 animate-spin" />
          Reconnecting to DockMon…
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
                onClick={() => void loadJob(true)}
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
                        item.status === 'error'
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
      {job && (job.status === 'completed' || job.status === 'partial') && (
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
