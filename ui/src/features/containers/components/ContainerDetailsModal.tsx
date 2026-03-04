/**
 * ContainerDetailsModal Component
 *
 * Full-screen modal for detailed container information
 * - Header with container name, icon, uptime, update status
 * - Action buttons (Start/Stop/Restart/Shell)
 * - Auto-restart toggle and desired state controls
 * - Tabbed interface: Info, Logs, Events, Alerts, Updates
 * - Info tab: 2-column layout with status, image, labels, ports, volumes, env vars
 */

import { useState, useEffect, useMemo, useCallback } from 'react'
import { useAuth } from '@/features/auth/AuthContext'
import { X, Play, RotateCw, Circle, Trash2, Skull, PenLine } from 'lucide-react'
import { Tabs } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { ConfirmModal } from '@/components/shared/ConfirmModal'
import type { Container } from '../types'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { useQueryClient } from '@tanstack/react-query'
import { useStatsContext } from '@/lib/stats/StatsProvider'
import { parseCompositeKey } from '@/lib/utils/containerKeys'
import { useContainerModal } from '@/providers/ContainerModalProvider'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'

// Import tab content components
import { ContainerInfoTab } from './modal-tabs/ContainerInfoTab'
import { ContainerModalEventsTab } from './modal-tabs/ContainerModalEventsTab'
import { ContainerModalLogsTab } from './modal-tabs/ContainerModalLogsTab'
import { ContainerModalAlertsTab } from './modal-tabs/ContainerModalAlertsTab'
import { ContainerUpdatesTab } from './modal-tabs/ContainerUpdatesTab'
import { ContainerHealthCheckTab } from './modal-tabs/ContainerHealthCheckTab'
import { ContainerShellTab } from './modal-tabs/ContainerShellTab'
import { DeleteContainerDialog } from './DeleteContainerDialog'

export interface ContainerDetailsModalProps {
  containerId: string | null
  container?: Container | null // Optional - modal will self-fetch if not provided
  open: boolean
  onClose: () => void
  initialTab?: string // Optional initial tab (defaults to 'info')
}

export function ContainerDetailsModal({
  containerId,
  container: externalContainer, // Rename to indicate external source
  open,
  onClose,
  initialTab = 'info',
}: ContainerDetailsModalProps) {
  const { hasCapability } = useAuth()
  const canOperate = hasCapability('containers.operate')
  const canViewLogs = hasCapability('containers.logs')
  const canShell = hasCapability('containers.shell')
  const canViewHealthChecks = hasCapability('healthchecks.view')
  const queryClient = useQueryClient()
  const { containerStats } = useStatsContext()
  const { updateContainerId } = useContainerModal()
  const { addMessageHandler } = useWebSocketContext()
  const [activeTab, setActiveTab] = useState(initialTab)
  const [uptime, setUptime] = useState<string>('')
  const [isPerformingAction, setIsPerformingAction] = useState(false)
  const [fallbackContainer, setFallbackContainer] = useState<Container | null>(null)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [showKillConfirm, setShowKillConfirm] = useState(false)
  const [showRenameDialog, setShowRenameDialog] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [renameError, setRenameError] = useState('')

  // Self-fetch container if not provided externally
  // This decouples the modal from the provider's data sources
  const container = useMemo(() => {
    // If modal is closed or no containerId, return null
    if (!open || !containerId) return null

    // If container provided externally (backward compatibility), use it
    if (externalContainer) return externalContainer

    // Parse composite key
    const { hostId, containerId: cId } = parseCompositeKey(containerId)

    // Try React Query cache first (fast lookup, no API call)
    // Used when modal opened from container list page
    const cached = queryClient.getQueryData<Container[]>(['containers'])
    if (cached) {
      const found = cached.find((c) => c.host_id === hostId && c.id === cId)
      if (found) return found
    }

    // Try StatsProvider (WebSocket data)
    // Used when modal opened from dashboard
    const stats = containerStats.get(containerId)
    if (stats) {
      return stats as Container
    }

    // Use fallback during data gap (container recreated but not yet in cache)
    // This prevents modal from closing during the 0-2s between container recreation
    // and the next monitoring poll that updates the caches with the new container ID
    if (fallbackContainer) {
      return fallbackContainer
    }

    // Container not found in any source
    // In practice, this should rarely happen since modal is opened
    // from pages that already have the container data loaded
    return null
  }, [open, containerId, externalContainer, queryClient, containerStats, fallbackContainer])

  // Update active tab when initialTab changes
  useEffect(() => {
    if (open) {
      setActiveTab(initialTab)
    }
  }, [open, initialTab])

  // Calculate uptime
  useEffect(() => {
    if (!container?.created) return

    const updateUptime = () => {
      const startTime = new Date(container.created)
      const now = new Date()
      const diff = now.getTime() - startTime.getTime()

      const days = Math.floor(diff / (1000 * 60 * 60 * 24))
      const hours = Math.floor((diff % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60))

      if (days > 0) {
        setUptime(`${days}d ${hours}h`)
      } else if (hours > 0) {
        setUptime(`${hours}h ${minutes}m`)
      } else {
        setUptime(`${minutes}m`)
      }
    }

    updateUptime()
    const interval = setInterval(updateUptime, 60000) // Update every minute

    return () => clearInterval(interval)
  }, [container?.created])

  // Listen for container recreations during updates (new ID, same name)
  // This prevents the modal from closing when a container is updated
  const handleContainerUpdate = useCallback(
    (message: any) => {
      if (!container || !containerId) return

      // Listen for container_recreated event (sent immediately when container gets new ID)
      if (message.type === 'container_recreated' && message.data) {
        const { old_composite_key, new_composite_key } = message.data

        // Check if this event is for the container we're currently viewing
        if (old_composite_key === containerId) {
          // CRITICAL: Save current container as fallback BEFORE updating ID
          // This prevents modal from closing during the 0-2s gap until monitoring poll arrives
          setFallbackContainer(container)

          updateContainerId(new_composite_key)
        }
      }
    },
    [container, containerId, updateContainerId]
  )

  useEffect(() => {
    if (!open || !container) return
    const cleanup = addMessageHandler(handleContainerUpdate)
    return cleanup
  }, [open, container, addMessageHandler, handleContainerUpdate])

  // Handle ESC key - stop propagation so parent modals don't also close
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        // Let sub-dialogs handle their own ESC
        if (showRenameDialog || showKillConfirm) return
        e.stopImmediatePropagation()
        onClose()
      }
    }

    if (open) {
      // Use capture phase to handle before other listeners
      document.addEventListener('keydown', handleEscape, true)
      document.body.style.overflow = 'hidden'
    }

    return () => {
      document.removeEventListener('keydown', handleEscape, true)
      document.body.style.overflow = ''
    }
  }, [open, onClose, showRenameDialog, showKillConfirm])

  if (!open || !containerId || !container) return null

  const isRunning = container.state === 'running'
  const isKillable = container.state === 'running' || container.state === 'paused' || container.state === 'restarting'
  const nameLower = container.name.toLowerCase()
  const isDockMon = nameLower === 'dockmon' || nameLower.startsWith('dockmon-')

  const handleAction = async (action: 'start' | 'stop' | 'restart') => {
    setIsPerformingAction(true)
    try {
      // CRITICAL: Use current tracked containerId, not container.id which may be stale from fallback
      const { hostId, containerId: currentId } = parseCompositeKey(containerId!)
      await apiClient.post(`/hosts/${hostId}/containers/${currentId}/${action}`)
      const labels = { start: 'Started', stop: 'Stopped', restart: 'Restarting' } as const
      toast.success(`${labels[action]} ${container.name}`)
    } catch (error) {
      toast.error(`Failed to ${action} container: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsPerformingAction(false)
    }
  }

  const handleDelete = async (removeVolumes: boolean) => {
    setIsPerformingAction(true)
    try {
      const { hostId, containerId: currentId } = parseCompositeKey(containerId!)
      await apiClient.delete(`/hosts/${hostId}/containers/${currentId}`, {
        params: { removeVolumes },
      })
      toast.success(`Container ${container.name} deleted successfully`)
      // Close modal after successful deletion
      onClose()
    } catch (error) {
      toast.error(`Failed to delete container: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsPerformingAction(false)
    }
  }

  const handleKill = async () => {
    setIsPerformingAction(true)
    try {
      const { hostId, containerId: currentId } = parseCompositeKey(containerId!)
      await apiClient.post(`/hosts/${hostId}/containers/${currentId}/kill`)
      toast.success(`Killed ${container.name}`)
    } catch (error) {
      toast.error(`Failed to kill container: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsPerformingAction(false)
    }
  }

  const validateContainerName = (name: string): string => {
    if (!name) return ''
    if (name.length > 255) return 'Name must be 255 characters or fewer'
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/.test(name)) {
      return 'Must start with alphanumeric and contain only alphanumeric, underscore, period, or hyphen'
    }
    return ''
  }

  const handleRename = async () => {
    const trimmed = renameValue.trim()
    if (!trimmed) return
    const error = validateContainerName(trimmed)
    if (error) {
      setRenameError(error)
      return
    }
    setIsPerformingAction(true)
    try {
      const { hostId, containerId: currentId } = parseCompositeKey(containerId!)
      await apiClient.post(`/hosts/${hostId}/containers/${currentId}/rename`, { name: trimmed })
      toast.success(`Renamed container to ${trimmed}`)
      setShowRenameDialog(false)
      setRenameValue('')
      setRenameError('')
    } catch (error) {
      toast.error(`Failed to rename container: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsPerformingAction(false)
    }
  }

  const getStatusColor = () => {
    switch (container.state.toLowerCase()) {
      case 'running':
        return 'text-success fill-success'
      case 'paused':
        return 'text-warning fill-warning'
      case 'restarting':
        return 'text-info fill-info'
      case 'exited':
      case 'dead':
        return 'text-danger fill-danger'
      default:
        return 'text-muted-foreground fill-muted-foreground'
    }
  }

  const tabs = [
    {
      id: 'info',
      label: 'Info',
      content: <ContainerInfoTab container={container} />,
    },
    ...(canViewLogs ? [{
      id: 'logs',
      label: 'Logs',
      content: <ContainerModalLogsTab hostId={container.host_id!} containerId={container.id} containerName={container.name} />,
    }] : []),
    ...(canShell ? [{
      id: 'shell',
      label: 'Shell',
      content: <ContainerShellTab hostId={container.host_id!} containerId={container.id} containerName={container.name} isRunning={isRunning} />,
    }] : []),
    {
      id: 'events',
      label: 'Events',
      content: <ContainerModalEventsTab hostId={container.host_id!} containerId={container.id} />,
    },
    {
      id: 'alerts',
      label: 'Alerts',
      content: <ContainerModalAlertsTab container={container} />,
    },
    {
      id: 'updates',
      label: 'Updates',
      content: <ContainerUpdatesTab container={container} />,
    },
    ...(canViewHealthChecks ? [{
      id: 'health',
      label: 'Health Check',
      content: <ContainerHealthCheckTab container={container} />,
    }] : []),
  ]

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/70 z-50 transition-opacity duration-200"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal */}
      <div
        role="dialog"
        aria-modal="true"
        className="fixed inset-0 z-50 flex items-center justify-center p-0 md:p-4"
        onClick={onClose}
      >
        <div
          className="relative w-full h-full md:w-[90vw] md:h-[90vh] bg-surface border-0 md:border border-border md:rounded-2xl shadow-2xl flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-4">
            {/* Container Icon - using first letter of name */}
            <div className="w-12 h-12 rounded bg-primary/10 flex items-center justify-center">
              <span className="text-xl font-semibold text-primary">
                {container.name.charAt(0).toUpperCase()}
              </span>
            </div>

            {/* Container Info */}
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-xl font-semibold" data-testid="container-name">
                  {container.name}
                  <span className="text-muted-foreground ml-2">({container.host_name})</span>
                </h2>
                {/* Update available badge - placeholder */}
                {/* <span className="px-2 py-0.5 text-xs bg-info/10 text-info rounded">Update available</span> */}
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Circle className={`w-3 h-3 ${getStatusColor()}`} />
                <span className="capitalize" data-testid="container-status">{container.state}</span>
                <span>•</span>
                <span>Uptime: {uptime}</span>
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2">
            <fieldset disabled={!canOperate} className="flex items-center gap-2 disabled:opacity-60">
              {!isRunning ? (
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => handleAction('start')}
                  disabled={isPerformingAction}
                >
                  <Play className="w-4 h-4 mr-2" />
                  Start
                </Button>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleAction('stop')}
                  disabled={isPerformingAction}
                  className="border-red-500/50 text-red-400 hover:bg-red-500/10"
                >
                  <Circle className="w-4 h-4 mr-2" />
                  Stop
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleAction('restart')}
                disabled={isPerformingAction}
              >
                <RotateCw className="w-4 h-4 mr-2" />
                Restart
              </Button>
              {isKillable && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowKillConfirm(true)}
                  disabled={isPerformingAction || isDockMon}
                  className="border-red-700/50 text-red-500 hover:bg-red-700/10"
                  title="Force kill (SIGKILL) - for unresponsive containers"
                >
                  <Skull className="w-4 h-4 mr-2" />
                  Kill
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setRenameValue(container.name)
                  setRenameError('')
                  setShowRenameDialog(true)
                }}
                disabled={isPerformingAction || isDockMon}
              >
                <PenLine className="w-4 h-4 mr-2" />
                Rename
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setShowDeleteDialog(true)}
                disabled={isPerformingAction || isDockMon}
                className="bg-red-600 hover:bg-red-700 text-white"
              >
                <Trash2 className="w-4 h-4 mr-2" />
                Delete
              </Button>
            </fieldset>
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
            >
              <X className="w-5 h-5" />
            </Button>
          </div>
        </div>

        {/* Tabs */}
        <Tabs
          tabs={tabs}
          activeTab={activeTab}
          onTabChange={setActiveTab}
        />
        </div>
      </div>

      {/* Delete Confirmation Dialog */}
      <DeleteContainerDialog
        isOpen={showDeleteDialog}
        onClose={() => setShowDeleteDialog(false)}
        onConfirm={handleDelete}
        containerName={container.name}
        containerImage={container.image}
        isDockMon={isDockMon}
      />

      {/* Rename Dialog */}
      {showRenameDialog && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-[60]"
            onClick={() => setShowRenameDialog(false)}
          />
          <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
            <div
              className="bg-surface border border-border rounded-lg shadow-xl w-full max-w-md p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 className="text-lg font-semibold mb-4">Rename Container</h3>
              <input
                type="text"
                value={renameValue}
                onChange={(e) => {
                  setRenameValue(e.target.value)
                  setRenameError(validateContainerName(e.target.value.trim()))
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !renameError) handleRename()
                  if (e.key === 'Escape') setShowRenameDialog(false)
                }}
                className={`w-full px-3 py-2 bg-background border rounded-md text-foreground focus:outline-none focus:ring-2 focus:ring-primary ${renameError ? 'border-red-500' : 'border-border'}`}
                placeholder="New container name"
                autoFocus
                maxLength={255}
              />
              {renameError && (
                <p className="text-xs text-red-400 mt-1">{renameError}</p>
              )}
              <div className="flex justify-end gap-2 mt-4">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowRenameDialog(false)}
                >
                  Cancel
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  onClick={handleRename}
                  disabled={!renameValue.trim() || !!renameError || renameValue.trim() === container.name || isPerformingAction}
                >
                  Rename
                </Button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Kill Confirmation Dialog */}
      <ConfirmModal
        isOpen={showKillConfirm}
        onClose={() => setShowKillConfirm(false)}
        onConfirm={() => {
          setShowKillConfirm(false)
          handleKill()
        }}
        title="Kill Container"
        description={`This sends SIGKILL to ${container.name}, terminating it immediately with no chance for graceful shutdown. This may cause data loss or corruption.`}
        confirmText="Kill Container"
        variant="danger"
      >
        <p className="text-sm text-muted-foreground">
          Use this only for unresponsive containers that will not stop gracefully.
        </p>
      </ConfirmModal>
    </>
  )
}
