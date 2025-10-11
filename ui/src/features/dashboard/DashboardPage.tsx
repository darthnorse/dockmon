/**
 * Dashboard Page - Phase 4c
 *
 * FEATURES:
 * - View mode selector (Compact | Standard | Expanded)
 * - Drag-and-drop widget dashboard (react-grid-layout)
 * - Real-time monitoring widgets
 * - Persistent layout (localStorage) and view mode (backend)
 * - Responsive grid system
 * - Host cards below widget grid (Standard/Expanded modes)
 * - WebSocket live sparkline updates (2s interval via query invalidation)
 */

import { useState } from 'react'
import { GridDashboard } from './GridDashboard'
import { ViewModeSelector } from './components/ViewModeSelector'
import { HostCardContainer } from './components/HostCardContainer'
import { HostCardsGrid } from './HostCardsGrid'
import { KpiBar } from './components/KpiBar'
import { CompactHostCard } from './components/CompactHostCard'
import { useViewMode } from './hooks/useViewMode'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import { useDashboardPrefs } from '@/hooks/useUserPrefs'
import { HostDrawer } from '@/features/hosts/components/drawer/HostDrawer'
import { HostDetailsModal } from '@/features/hosts/components/HostDetailsModal'
import { HostModal } from '@/features/hosts/components/HostModal'
import { debug } from '@/lib/debug'

export function DashboardPage() {
  const { viewMode, setViewMode, isLoading: isViewModeLoading } = useViewMode()
  const { data: hosts, isLoading: isHostsLoading } = useHosts()
  const { dashboardPrefs } = useDashboardPrefs()

  // Drawer state
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedHostId, setSelectedHostId] = useState<string | null>(null)

  // Details Modal state
  const [modalOpen, setModalOpen] = useState(false)

  // Edit Modal state
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editingHost, setEditingHost] = useState<typeof selectedHost | null>(null)

  const selectedHost = hosts?.find(h => h.id === selectedHostId)

  const handleHostClick = (hostId: string) => {
    setSelectedHostId(hostId)
    setDrawerOpen(true)
  }

  const showKpiBar = dashboardPrefs?.showKpiBar ?? true
  const showStatsWidgets = dashboardPrefs?.showStatsWidgets ?? false

  return (
    <div className="flex flex-col h-full gap-4 p-4">
      {/* View Mode Selector - Phase 4b */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <ViewModeSelector viewMode={viewMode} onChange={setViewMode} disabled={isViewModeLoading} />
      </div>

      {/* KPI Bar - Phase 4c */}
      {showKpiBar && <KpiBar />}

      {/* Widget Grid - Phase 3b */}
      {showStatsWidgets && <GridDashboard />}

      {/* View Mode Content - Phase 4c/4d */}
      {viewMode === 'compact' && (
        <div className="mt-4">
          <h2 className="text-lg font-semibold mb-4">Hosts</h2>
          {isHostsLoading ? (
            <div className="text-muted-foreground">Loading hosts...</div>
          ) : hosts && hosts.length > 0 ? (
            <div className="flex flex-col gap-2">
              {hosts.map((host) => (
                <CompactHostCard
                  key={host.id}
                  host={{
                    id: host.id,
                    name: host.name,
                    url: host.url,
                    status: host.status as 'online' | 'offline' | 'error',
                    ...(host.tags && { tags: host.tags }),
                  }}
                  onClick={() => handleHostClick(host.id)}
                />
              ))}
            </div>
          ) : (
            <div className="p-8 border border-dashed border-border rounded-lg text-center text-muted-foreground">
              No hosts configured. Add a host to get started.
            </div>
          )}
        </div>
      )}

      {viewMode === 'standard' && (
        <div className="mt-4">
          <h2 className="text-lg font-semibold mb-4">Hosts</h2>
          {isHostsLoading ? (
            <div className="text-muted-foreground">Loading hosts...</div>
          ) : hosts && hosts.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {hosts.map((host) => (
                <HostCardContainer
                  key={host.id}
                  host={{
                    id: host.id,
                    name: host.name,
                    url: host.url,
                    status: host.status as 'online' | 'offline' | 'error',
                    ...(host.tags && { tags: host.tags }),
                  }}
                  onHostClick={handleHostClick}
                />
              ))}
            </div>
          ) : (
            <div className="p-8 border border-dashed border-border rounded-lg text-center text-muted-foreground">
              No hosts configured. Add a host to get started.
            </div>
          )}
        </div>
      )}

      {viewMode === 'expanded' && hosts && (
        <HostCardsGrid
          hosts={hosts.map(h => ({
            id: h.id,
            name: h.name,
            url: h.url,
            status: h.status as 'online' | 'offline' | 'error',
            ...(h.tags && { tags: h.tags }),
          }))}
          onHostClick={handleHostClick}
        />
      )}

      {/* Host Drawer */}
      <HostDrawer
        hostId={selectedHostId}
        host={selectedHost}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false)
          setSelectedHostId(null)
        }}
        onEdit={(hostId) => {
          const host = hosts?.find(h => h.id === hostId)
          if (host) {
            setEditingHost(host)
            setEditModalOpen(true)
          }
          setDrawerOpen(false)
        }}
        onDelete={(hostId) => {
          // TODO: Open delete confirmation dialog
          debug.log('DashboardPage', 'Delete host:', hostId)
        }}
        onExpand={() => {
          setDrawerOpen(false)
          setModalOpen(true)
        }}
      />

      {/* Host Details Modal */}
      <HostDetailsModal
        hostId={selectedHostId}
        host={selectedHost}
        open={modalOpen}
        onClose={() => {
          setModalOpen(false)
        }}
      />

      {/* Edit Host Modal */}
      <HostModal
        isOpen={editModalOpen}
        onClose={() => {
          setEditModalOpen(false)
          setEditingHost(null)
        }}
        host={editingHost ?? null}
      />
    </div>
  )
}
