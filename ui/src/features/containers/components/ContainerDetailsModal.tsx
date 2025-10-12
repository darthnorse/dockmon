/**
 * ContainerDetailsModal Component
 *
 * Full-screen modal for detailed container information
 * - Header with container name, icon, uptime, update status
 * - Action buttons (Start/Stop/Restart/Shell)
 * - Auto-restart toggle and desired state controls
 * - Tabbed interface: Info, Live Stats, Logs, Events, Alerts, Updates
 * - Info tab: 2-column layout with status, image, labels, ports, volumes, env vars
 */

import { useState, useEffect } from 'react'
import { X, Play, RotateCw, Terminal, Copy, Circle } from 'lucide-react'
import { Tabs } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import type { Container } from '../types'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'

// Import tab content components
import { ContainerInfoTab } from './modal-tabs/ContainerInfoTab'
import { ContainerModalEventsTab } from './modal-tabs/ContainerModalEventsTab'

export interface ContainerDetailsModalProps {
  containerId: string | null
  container: Container | null | undefined
  open: boolean
  onClose: () => void
}

export function ContainerDetailsModal({
  containerId,
  container,
  open,
  onClose,
}: ContainerDetailsModalProps) {
  const [activeTab, setActiveTab] = useState('info')
  const [uptime, setUptime] = useState<string>('')
  const [isPerformingAction, setIsPerformingAction] = useState(false)

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

  // Reset to Info tab when modal opens
  useEffect(() => {
    if (open) {
      setActiveTab('info')
    }
  }, [open])

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

  const handleCopyId = () => {
    navigator.clipboard.writeText(container.id)
    toast.success('Container ID copied to clipboard')
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
      id: 'stats',
      label: 'Live Stats',
      content: <div className="p-6 text-muted-foreground">Live Stats coming soon...</div>,
    },
    {
      id: 'logs',
      label: 'Logs',
      content: <div className="p-6 text-muted-foreground">Logs coming soon...</div>,
    },
    {
      id: 'events',
      label: 'Events',
      content: <ContainerModalEventsTab hostId={container.host_id!} containerId={container.id} />,
    },
    {
      id: 'alerts',
      label: 'Alerts',
      content: <div className="p-6 text-muted-foreground">Alerts coming soon...</div>,
    },
    {
      id: 'updates',
      label: 'Updates',
      content: <div className="p-6 text-muted-foreground">Updates coming soon...</div>,
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
                <h2 className="text-xl font-semibold">
                  {container.name}
                  <span className="text-muted-foreground ml-2">({container.host_name})</span>
                </h2>
                {/* Update available badge - placeholder */}
                {/* <span className="px-2 py-0.5 text-xs bg-info/10 text-info rounded">Update available</span> */}
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Circle className={`w-3 h-3 ${getStatusColor()}`} />
                <span className="capitalize">{container.state}</span>
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
              variant="outline"
              size="sm"
              onClick={() => toast.info('Shell access coming soon...')}
            >
              <Terminal className="w-4 h-4 mr-2" />
              Shell
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCopyId}
            >
              <Copy className="w-4 h-4 mr-2" />
              Copy ID
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
