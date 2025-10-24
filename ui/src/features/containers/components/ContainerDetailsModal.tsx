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
import { X, Play, RotateCw, Circle } from 'lucide-react'
import { Tabs } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
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
  const queryClient = useQueryClient()
  const { containerStats } = useStatsContext()
  const { updateContainerId } = useContainerModal()
  const { addMessageHandler } = useWebSocketContext()
  const [activeTab, setActiveTab] = useState(initialTab)
  const [uptime, setUptime] = useState<string>('')
  const [isPerformingAction, setIsPerformingAction] = useState(false)

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

    // Container not found in any source
    // In practice, this should rarely happen since modal is opened
    // from pages that already have the container data loaded
    return null
  }, [open, containerId, externalContainer, queryClient, containerStats])

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

      // Check if this is a container_update message for the same container name but different ID
      if (message.type === 'container_update' && message.data) {
        const updatedContainer = message.data

        // Same host and name, but different ID = container was recreated
        if (
          updatedContainer.host_id === container.host_id &&
          updatedContainer.name === container.name &&
          updatedContainer.id &&  // Ensure new ID exists before comparing
          updatedContainer.id !== container.id
        ) {
          const newCompositeKey = `${updatedContainer.host_id}:${updatedContainer.id}`
          console.log(`Container ${container.name} recreated with new ID, updating modal tracking:`, {
            old: containerId,
            new: newCompositeKey,
          })
          updateContainerId(newCompositeKey)
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

  // Handle ESC key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        onClose()
      }
    }

    if (open) {
      document.addEventListener('keydown', handleEscape)
      document.body.style.overflow = 'hidden'
    }

    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open || !containerId || !container) return null

  const isRunning = container.state === 'running'

  const handleStart = async () => {
    setIsPerformingAction(true)
    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${container.id}/start`)
      toast.success(`Started ${container.name}`)
    } catch (error) {
      toast.error(`Failed to start container: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsPerformingAction(false)
    }
  }

  const handleStop = async () => {
    setIsPerformingAction(true)
    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${container.id}/stop`)
      toast.success(`Stopped ${container.name}`)
    } catch (error) {
      toast.error(`Failed to stop container: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsPerformingAction(false)
    }
  }

  const handleRestart = async () => {
    setIsPerformingAction(true)
    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${container.id}/restart`)
      toast.success(`Restarting ${container.name}`)
    } catch (error) {
      toast.error(`Failed to restart container: ${error instanceof Error ? error.message : 'Unknown error'}`)
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
    {
      id: 'logs',
      label: 'Logs',
      content: <ContainerModalLogsTab hostId={container.host_id!} containerId={container.id} containerName={container.name} />,
    },
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
    {
      id: 'health',
      label: 'Health Check',
      content: <ContainerHealthCheckTab container={container} />,
    },
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
            {!isRunning ? (
              <Button
                variant="default"
                size="sm"
                onClick={handleStart}
                disabled={isPerformingAction}
              >
                <Play className="w-4 h-4 mr-2" />
                Start
              </Button>
            ) : (
              <Button
                variant="destructive"
                size="sm"
                onClick={handleStop}
                disabled={isPerformingAction}
              >
                <Circle className="w-4 h-4 mr-2" />
                Stop
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={handleRestart}
              disabled={isPerformingAction}
            >
              <RotateCw className="w-4 h-4 mr-2" />
              Restart
            </Button>
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
    </>
  )
}
