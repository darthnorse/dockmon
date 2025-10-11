/**
 * HostDetailsModal Component
 *
 * Full-page modal for detailed host inspection
 * Triggered by "Expand" button in Host Drawer
 *
 * DESIGN:
 * - Breadcrumb navigation (Hosts > hostname)
 * - KPI cards (Containers, Running, Stopped, Alerts)
 * - 6 tabs: Overview, Containers, Live Stats, Events, Logs, Settings
 * - Overview: Large performance charts + Host Info + Events sidebar
 * - Time range selector
 * - Restart button + more menu
 */

import { useState, useEffect } from 'react'
import { X, ChevronRight, MoreVertical, RotateCw } from 'lucide-react'
import { Tabs } from '@/components/ui/tabs'
import { useContainerCounts } from '@/lib/stats/StatsProvider'

// Import tab content components
import { HostOverviewTab } from './modal-tabs/HostOverviewTab'
import { HostContainersTab } from './modal-tabs/HostContainersTab'
import { HostEventsTab } from './modal-tabs/HostEventsTab'
import { HostLogsTab } from './modal-tabs/HostLogsTab'

export interface HostDetailsModalProps {
  /**
   * Host ID to display
   */
  hostId: string | null

  /**
   * Host data (from useHosts query)
   */
  host: any

  /**
   * Whether modal is open
   */
  open: boolean

  /**
   * Callback when modal closes
   */
  onClose: () => void
}

export function HostDetailsModal({
  hostId,
  host,
  open,
  onClose,
}: HostDetailsModalProps) {
  const [activeTab, setActiveTab] = useState('overview')
  const containerCounts = useContainerCounts(hostId || '')

  // Handle ESC key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        onClose()
      }
    }

    if (open) {
      document.addEventListener('keydown', handleEscape)
      // Prevent body scroll when modal is open
      document.body.style.overflow = 'hidden'
    }

    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  // Reset to Overview tab when modal opens
  useEffect(() => {
    if (open) {
      setActiveTab('overview')
    }
  }, [open])

  if (!open || !hostId || !host) return null

  const tabs = [
    {
      id: 'overview',
      label: 'Overview',
      content: <HostOverviewTab hostId={hostId} host={host} />,
    },
    {
      id: 'containers',
      label: 'Containers',
      content: <HostContainersTab hostId={hostId} />,
    },
    {
      id: 'events',
      label: 'Events',
      content: <HostEventsTab hostId={hostId} />,
    },
    {
      id: 'logs',
      label: 'Logs',
      content: <HostLogsTab hostId={hostId} />,
    },
  ]

  // Calculate alert count (placeholder - you'll need to implement this)
  const alertCount = 0 // TODO: Get from actual alerts

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
        aria-labelledby="modal-title"
        className="fixed inset-0 z-50 flex items-center justify-center p-0 md:p-4"
        onClick={onClose}
      >
        <div
          className="relative w-full h-full md:w-[90vw] md:h-[90vh] bg-background border-0 md:border border-border md:rounded-2xl shadow-2xl flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
            {/* Breadcrumb */}
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Hosts</span>
              <ChevronRight className="h-4 w-4" />
              <span id="modal-title" className="text-foreground font-medium">
                {host.name}
              </span>
            </div>

            {/* Actions */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  // TODO: Implement restart
                  console.log('Restart host')
                }}
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border hover:bg-muted transition-colors text-sm"
              >
                <RotateCw className="h-4 w-4" />
                <span>Restart</span>
              </button>

              <button
                className="p-2 rounded-lg border border-border hover:bg-muted transition-colors"
                onClick={() => {
                  // TODO: Implement more menu
                  console.log('More menu')
                }}
              >
                <MoreVertical className="h-4 w-4" />
              </button>

              <button
                onClick={onClose}
                className="p-2 rounded-lg hover:bg-muted transition-colors focus:outline-none focus:ring-2 focus:ring-accent ml-2"
                aria-label="Close modal"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
          </div>

          {/* KPI Cards */}
          <div className="grid grid-cols-4 gap-4 px-6 py-4 border-b border-border shrink-0">
            {/* Total Containers */}
            <div className="bg-surface-2 rounded-lg p-4 border border-border">
              <div className="text-3xl font-bold">
                {containerCounts.total || 0}
              </div>
              <div className="text-sm text-muted-foreground mt-1">Containers</div>
            </div>

            {/* Running */}
            <div className="bg-surface-2 rounded-lg p-4 border border-border">
              <div className="text-3xl font-bold text-green-500">
                {containerCounts.running || 0}
              </div>
              <div className="text-sm text-muted-foreground mt-1">Running</div>
            </div>

            {/* Stopped */}
            <div className="bg-surface-2 rounded-lg p-4 border border-border">
              <div className="text-3xl font-bold">
                {(containerCounts.total || 0) - (containerCounts.running || 0)}
              </div>
              <div className="text-sm text-muted-foreground mt-1">Stopped</div>
            </div>

            {/* Alerts */}
            <div className="bg-surface-2 rounded-lg p-4 border border-border">
              <div className={`text-3xl font-bold ${alertCount > 0 ? 'text-red-500' : ''}`}>
                {alertCount}
              </div>
              <div className="text-sm text-muted-foreground mt-1">Alerts</div>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex-1 overflow-hidden flex flex-col">
            <Tabs
              tabs={tabs}
              activeTab={activeTab}
              onTabChange={setActiveTab}
              className="flex-1 overflow-hidden flex flex-col"
            />
          </div>
        </div>
      </div>
    </>
  )
}
