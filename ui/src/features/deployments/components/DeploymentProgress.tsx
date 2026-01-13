/**
 * Deployment Progress Component
 *
 * Shows real-time deployment progress via WebSocket.
 * Displays:
 * - Progress bar with percentage
 * - Current stage/status
 * - Error message if deployment fails
 * - Log-style messages as deployment progresses
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { CheckCircle2, XCircle, Loader2, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import type { WebSocketMessage } from '@/lib/websocket/useWebSocket'

interface DeploymentProgressProps {
  deploymentId: string | null
  stackName: string
  hostName: string
  onBack: () => void
  onComplete: () => void
}

interface LogEntry {
  id: string
  timestamp: Date
  message: string
  type: 'info' | 'success' | 'error'
}

// Generate unique ID for log entries
let logIdCounter = 0
function generateLogId(): string {
  return `log-${Date.now()}-${++logIdCounter}`
}

// Check if a message's deployment ID matches our target
function isDeploymentMatch(messageId: string | undefined, targetId: string): boolean {
  if (!messageId || !targetId) return false
  // Exact match
  if (messageId === targetId) return true
  // Composite key format: "host_id:deployment_id" - extract and compare the deployment part
  const parts = messageId.split(':')
  if (parts.length === 2 && parts[1] === targetId) return true
  return false
}

// Map backend status to display info
function getStatusDisplay(status: string): { label: string; type: 'info' | 'success' | 'error' } {
  switch (status) {
    case 'pending':
      return { label: 'Pending...', type: 'info' }
    case 'pulling_image':
      return { label: 'Pulling images...', type: 'info' }
    case 'creating':
      return { label: 'Creating containers...', type: 'info' }
    case 'starting':
      return { label: 'Starting containers...', type: 'info' }
    case 'running':
      return { label: 'Deployment complete', type: 'success' }
    case 'partial':
      return { label: 'Partially deployed', type: 'error' }
    case 'failed':
      return { label: 'Deployment failed', type: 'error' }
    case 'stopped':
      return { label: 'Stopped', type: 'info' }
    default:
      return { label: status, type: 'info' }
  }
}

export function DeploymentProgress({
  deploymentId,
  stackName,
  hostName,
  onBack,
  onComplete,
}: DeploymentProgressProps) {
  const { addMessageHandler } = useWebSocketContext()

  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState('pending')
  const [error, setError] = useState<string | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [isComplete, setIsComplete] = useState(false)

  const logsEndRef = useRef<HTMLDivElement>(null)

  // Refs to avoid stale closures in WebSocket handler
  const statusRef = useRef(status)
  const hasLoggedStartRef = useRef(false)

  // Keep statusRef in sync
  useEffect(() => {
    statusRef.current = status
  }, [status])

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  // Add log entry
  const addLog = useCallback((message: string, type: LogEntry['type'] = 'info') => {
    setLogs((prev) => [...prev, { id: generateLogId(), timestamp: new Date(), message, type }])
  }, [])

  // Subscribe to WebSocket messages
  useEffect(() => {
    if (!deploymentId) return

    // Only log start message once
    if (!hasLoggedStartRef.current) {
      addLog(`Starting deployment of "${stackName}" to ${hostName}...`)
      hasLoggedStartRef.current = true
    }

    const cleanup = addMessageHandler((message: WebSocketMessage) => {
      // Handle deployment progress
      if (message.type === 'deployment_progress') {
        // Check if this message is for our deployment
        if (!isDeploymentMatch(message.deployment_id, deploymentId)) {
          return
        }

        const { status: newStatus, progress: progressData, error: errorMsg } = message

        // Update progress
        if (progressData) {
          setProgress(progressData.overall_percent || 0)
        }

        // Update status
        if (newStatus) {
          const prevStatus = statusRef.current
          setStatus(newStatus)

          // Log status changes
          if (newStatus !== prevStatus) {
            const display = getStatusDisplay(newStatus)
            addLog(display.label, display.type)
          }
        }

        // Handle error
        if (errorMsg) {
          setError(errorMsg)
          addLog(`Error: ${errorMsg}`, 'error')
        }

        // Check if complete
        if (newStatus === 'running' || newStatus === 'partial' || newStatus === 'failed') {
          setIsComplete(true)
          setProgress(100)
          if (newStatus === 'running') {
            addLog('All containers started successfully', 'success')
          }
        }
      }

      // Handle layer progress (image pulls)
      if (message.type === 'deployment_layer_progress') {
        const { data } = message
        if (isDeploymentMatch(data.entity_id, deploymentId)) {
          setProgress(data.overall_progress || 0)
          if (data.summary) {
            // Update the last log entry or add new one for pull progress
            setLogs((prev) => {
              const lastLog = prev[prev.length - 1]
              if (lastLog && lastLog.message.startsWith('Pulling:')) {
                return [...prev.slice(0, -1), { ...lastLog, message: `Pulling: ${data.summary}` }]
              }
              return [...prev, { id: generateLogId(), timestamp: new Date(), message: `Pulling: ${data.summary}`, type: 'info' }]
            })
          }
        }
      }
    })

    return cleanup
  }, [deploymentId, stackName, hostName, addMessageHandler, addLog])

  const statusDisplay = getStatusDisplay(status)
  const isError = status === 'failed' || status === 'partial'
  const isSuccess = status === 'running'

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 shrink-0">
        <div>
          <h3 className="font-semibold text-lg">
            {isComplete ? (isSuccess ? 'Deployment Complete' : 'Deployment Finished') : 'Deploying...'}
          </h3>
          <p className="text-sm text-muted-foreground">
            {stackName} → {hostName}
          </p>
        </div>
        {isComplete && (
          <div className={cn(
            'flex items-center gap-2 px-3 py-1 rounded-full text-sm font-medium',
            isSuccess && 'bg-green-500/10 text-green-500',
            isError && 'bg-destructive/10 text-destructive'
          )}>
            {isSuccess ? (
              <>
                <CheckCircle2 className="h-4 w-4" />
                Success
              </>
            ) : (
              <>
                <XCircle className="h-4 w-4" />
                {status === 'partial' ? 'Partial' : 'Failed'}
              </>
            )}
          </div>
        )}
      </div>

      {/* Progress bar */}
      <div className="mb-4 shrink-0">
        <div className="flex items-center justify-between mb-2 text-sm">
          <span className={cn(
            'flex items-center gap-2',
            isError && 'text-destructive'
          )}>
            {!isComplete && <Loader2 className="h-4 w-4 animate-spin" />}
            {statusDisplay.label}
          </span>
          <span className="text-muted-foreground">{Math.round(progress)}%</span>
        </div>
        <Progress
          value={progress}
          className={cn(
            'h-2',
            isError && '[&>div]:bg-destructive',
            isSuccess && '[&>div]:bg-green-500'
          )}
        />
      </div>

      {/* Error message */}
      {error && (
        <div className="mb-4 p-3 bg-destructive/10 border border-destructive/20 rounded-md text-sm text-destructive shrink-0">
          {error}
        </div>
      )}

      {/* Log output */}
      <div className="flex-1 min-h-0 bg-muted/30 rounded-md border overflow-hidden">
        <div className="h-full overflow-y-auto p-3 font-mono text-xs space-y-1">
          {logs.map((log) => (
            <div
              key={log.id}
              className={cn(
                'flex gap-2',
                log.type === 'error' && 'text-destructive',
                log.type === 'success' && 'text-green-500'
              )}
            >
              <span className="text-muted-foreground shrink-0">
                {log.timestamp.toLocaleTimeString()}
              </span>
              <span>{log.message}</span>
            </div>
          ))}
          <div ref={logsEndRef} />
        </div>
      </div>

      {/* Actions */}
      <div className="flex justify-between pt-4 mt-4 border-t shrink-0">
        <Button variant="outline" onClick={onBack} className="gap-2">
          <ArrowLeft className="h-4 w-4" />
          Back to Editor
        </Button>
        {isComplete && (
          <Button onClick={onComplete}>
            Done
          </Button>
        )}
      </div>
    </div>
  )
}
