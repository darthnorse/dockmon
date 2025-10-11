/**
 * ContainerDrawer - Side panel for container details
 *
 * Slides in from the right (400-480px width)
 * Tabs: Overview (default), Live Stats, Events, Logs
 */

import { useState } from 'react'
import { Maximize2, MoreVertical, Play, Square, RotateCw, BellOff, EyeOff, Pin } from 'lucide-react'
import { Drawer } from '@/components/ui/drawer'
import { Tabs } from '@/components/ui/tabs'
import { ContainerOverviewTab } from './drawer/ContainerOverviewTab'
import { DropdownMenu, DropdownMenuItem, DropdownMenuSeparator } from '@/components/ui/dropdown-menu'
import { useContainer } from '@/lib/stats/StatsProvider'

interface ContainerDrawerProps {
  isOpen: boolean
  onClose: () => void
  containerId: string | null
  onExpand?: () => void
}

export function ContainerDrawer({ isOpen, onClose, containerId, onExpand }: ContainerDrawerProps) {
  const [activeTab, setActiveTab] = useState('overview')
  const container = useContainer(containerId)

  if (!containerId) return null

  const handleAction = (action: string) => {
    console.log(`Container action: ${action} for ${container?.name}`)
    // TODO: Implement API calls for each action
  }

  const tabs = [
    {
      id: 'overview',
      label: 'Overview',
      content: <ContainerOverviewTab containerId={containerId} />,
    },
    {
      id: 'stats',
      label: 'Live Stats',
      content: (
        <div className="p-4 text-muted-foreground text-sm">
          Live Stats - Coming soon
        </div>
      ),
    },
    {
      id: 'logs',
      label: 'Logs',
      content: (
        <div className="p-4 text-muted-foreground text-sm">
          Logs - Coming soon
        </div>
      ),
    },
    {
      id: 'events',
      label: 'Events',
      content: (
        <div className="p-4 text-muted-foreground text-sm">
          Events - Coming soon
        </div>
      ),
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
        {/* Actions Menu */}
        <DropdownMenu
          trigger={
            <button
              className="p-2 text-muted-foreground hover:text-foreground transition-colors"
              aria-label="More actions"
            >
              <MoreVertical className="w-4 h-4" />
            </button>
          }
          align="end"
        >
          {onExpand && (
            <>
              <DropdownMenuItem onClick={onExpand} icon={<Maximize2 className="w-4 h-4" />}>
                Open Full Details
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}

          {/* Start/Stop/Restart */}
          {container?.state === 'running' ? (
            <>
              <DropdownMenuItem onClick={() => handleAction('stop')} icon={<Square className="w-4 h-4" />}>
                Stop
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleAction('restart')} icon={<RotateCw className="w-4 h-4" />}>
                Restart
              </DropdownMenuItem>
            </>
          ) : (
            <DropdownMenuItem onClick={() => handleAction('start')} icon={<Play className="w-4 h-4" />}>
              Start
            </DropdownMenuItem>
          )}

          <DropdownMenuSeparator />

          <DropdownMenuItem onClick={() => handleAction('silence-alerts')} icon={<BellOff className="w-4 h-4" />}>
            Silence Alerts…
          </DropdownMenuItem>

          <DropdownMenuItem onClick={() => handleAction('toggle-visibility')} icon={<EyeOff className="w-4 h-4" />}>
            Hide on Dashboard
          </DropdownMenuItem>

          <DropdownMenuItem onClick={() => handleAction('toggle-pin')} icon={<Pin className="w-4 h-4" />}>
            Pin on Dashboard
          </DropdownMenuItem>
        </DropdownMenu>

        {/* Expand Button */}
        {onExpand && (
          <button
            onClick={onExpand}
            className="p-2 text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Expand to full view"
          >
            <Maximize2 className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Tabs */}
      <Tabs tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} className="h-full" />
    </Drawer>
  )
}
