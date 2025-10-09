/**
 * Host Cards Grid - Using react-grid-layout
 *
 * FEATURES:
 * - Drag-and-drop host card positioning
 * - Resizable cards (responsive container columns)
 * - Persistent layout per user
 * - Same UX as widget dashboard above
 */

import { useState, useCallback, useMemo } from 'react'
import GridLayout, { WidthProvider, type Layout } from 'react-grid-layout'
import { ExpandedHostCardContainer } from './components/ExpandedHostCardContainer'
import { useDashboardPrefs } from '@/hooks/useUserPrefs'
import { debug } from '@/lib/debug'
import 'react-grid-layout/css/styles.css'

const ResponsiveGridLayout = WidthProvider(GridLayout)

interface Host {
  id: string
  name: string
  url: string
  status: 'online' | 'offline' | 'error'
  tags?: string[]
}

interface HostCardsGridProps {
  hosts: Host[]
}

// Default layout for host cards (3 columns, each 4 grid units wide)
function generateDefaultLayout(hosts: Host[]): Layout[] {
  return hosts.map((host, index) => ({
    i: host.id,
    x: (index % 3) * 4, // 3 columns: 0, 4, 8
    y: Math.floor(index / 3) * 3, // Row height = 3
    w: 4, // Width: 4 units (12/3 = 3 columns)
    h: 3, // Height: 3 units
    minW: 3, // Minimum 3 units wide
    minH: 2, // Minimum 2 units tall
  }))
}

export function HostCardsGrid({ hosts }: HostCardsGridProps) {
  const { dashboardPrefs, updateDashboardPrefs } = useDashboardPrefs()

  // Get layout from user prefs or generate default
  const layout = useMemo(() => {
    const storedLayout = dashboardPrefs?.hostCardLayout as Layout[] | undefined

    if (storedLayout && storedLayout.length === hosts.length) {
      // Use stored layout
      return storedLayout
    }

    // Generate default layout
    return generateDefaultLayout(hosts)
  }, [hosts, dashboardPrefs])

  const [currentLayout, setCurrentLayout] = useState<Layout[]>(layout)

  // Handle layout change (drag/resize)
  const handleLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      setCurrentLayout(newLayout)

      // Save to user prefs (debounced via React Query)
      updateDashboardPrefs({
        hostCardLayout: newLayout,
      })

      debug.log('Host cards layout updated:', newLayout)
    },
    [updateDashboardPrefs]
  )

  return (
    <div className="mt-4">
      <h2 className="text-lg font-semibold mb-4">Hosts</h2>

      <ResponsiveGridLayout
        className="layout"
        layout={currentLayout}
        onLayoutChange={handleLayoutChange}
        cols={12}
        rowHeight={120}
        draggableHandle=".host-card-drag-handle"
        compactType="vertical"
        preventCollision={false}
      >
        {hosts.map((host) => (
          <div key={host.id} className="widget-container">
            {/* Drag handle - left side only to avoid blocking kebab menu */}
            <div className="host-card-drag-handle absolute left-0 top-0 z-10 h-16 cursor-move" style={{ width: 'calc(100% - 60px)' }} />

            {/* Host card content */}
            <div className="h-full overflow-hidden">
              <ExpandedHostCardContainer
                host={{
                  id: host.id,
                  name: host.name,
                  url: host.url,
                  status: host.status,
                  ...(host.tags && { tags: host.tags }),
                }}
              />
            </div>
          </div>
        ))}
      </ResponsiveGridLayout>

      {hosts.length === 0 && (
        <div className="p-8 border border-dashed border-border rounded-lg text-center text-muted-foreground">
          No hosts configured. Add a host to get started.
        </div>
      )}
    </div>
  )
}
