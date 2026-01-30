/**
 * ContainerDrawer - Side panel for container details
 *
 * Slides in from the right (400-480px width)
 * Tabs: Overview (default), Events, Logs
 */

import { useState } from 'react'
import { useAuth } from '@/features/auth/AuthContext'
import { Maximize2, Play, Square, RotateCw } from 'lucide-react'
import { Drawer } from '@/components/ui/drawer'
import { Tabs } from '@/components/ui/tabs'
import { ContainerOverviewTab } from './drawer/ContainerOverviewTab'
import { ContainerEventsTab } from './drawer/ContainerEventsTab'
import { ContainerLogsTab } from './drawer/ContainerLogsTab'
import { useContainer } from '@/lib/stats/StatsProvider'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'

interface ContainerDrawerProps {
  isOpen: boolean
  onClose: () => void
  containerId: string | null
  onExpand?: () => void
}

export function ContainerDrawer({ isOpen, onClose, containerId, onExpand }: ContainerDrawerProps) {
  const { hasCapability } = useAuth()
  const canOperate = hasCapability('containers.operate')
  const [activeTab, setActiveTab] = useState('overview')
  const [isActionLoading, setIsActionLoading] = useState(false)
  const container = useContainer(containerId)

  if (!containerId) return null

  const handleAction = async (action: 'start' | 'stop' | 'restart') => {
    if (!container) return

    setIsActionLoading(true)
    try {
      await apiClient.post(`/hosts/${container.host_id}/containers/${container.id}/${action}`)
      toast.success(`Container ${action === 'restart' ? 'restarting' : action === 'stop' ? 'stopping' : 'starting'}...`)
    } catch (error) {
      debug.error('ContainerDrawer', `Error ${action}ing container:`, error)
      toast.error(`Failed to ${action} container: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsActionLoading(false)
    }
  }

  // Action buttons to pass to Overview tab
  const actionButtons = (
    <fieldset disabled={!canOperate} className="flex gap-2 disabled:opacity-60">
      {container?.state === 'running' ? (
        <>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleAction('stop')}
            disabled={isActionLoading}
            className="text-danger hover:text-danger hover:bg-danger/10"
          >
            <Square className="w-3.5 h-3.5 mr-1.5" />
            Stop
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleAction('restart')}
            disabled={isActionLoading}
            className="text-info hover:text-info hover:bg-info/10"
          >
            <RotateCw className="w-3.5 h-3.5 mr-1.5" />
            Restart
          </Button>
        </>
      ) : (
        <Button
          variant="outline"
          size="sm"
          onClick={() => handleAction('start')}
          disabled={isActionLoading}
          className="text-success hover:text-success hover:bg-success/10"
        >
          <Play className="w-3.5 h-3.5 mr-1.5" />
          Start
        </Button>
      )}
    </fieldset>
  )

  const tabs = [
    {
      id: 'overview',
      label: 'Overview',
      content: <ContainerOverviewTab containerId={containerId} actionButtons={actionButtons} />,
    },
    {
      id: 'events',
      label: 'Events',
      content: container ? (
        <ContainerEventsTab hostId={container.host_id} containerId={container.id} />
      ) : (
        <div className="p-4 text-muted-foreground text-sm">
          Loading...
        </div>
      ),
    },
    {
      id: 'logs',
      label: 'Logs',
      content: <ContainerLogsTab containerId={containerId} />,
    },
  ]

  return (
    <Drawer
      open={isOpen}
      onClose={onClose}
      title="Container Details"
      width="w-[480px]"
    >
      {/* Header Actions */}
      <div className="absolute top-6 right-16 flex gap-2">
        {/* Expand Button */}
        {onExpand && (
          <button
            onClick={onExpand}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-accent hover:bg-accent/90 text-accent-foreground transition-colors text-sm"
          >
            <Maximize2 className="h-4 w-4" />
            <span>Expand</span>
          </button>
        )}
      </div>

      {/* Tabs */}
      <Tabs tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} className="h-full" />
    </Drawer>
  )
}
