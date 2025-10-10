/**
 * Host Cards Grid - Using react-grid-layout
 *
 * FEATURES:
 * - Drag-and-drop host card positioning
 * - Resizable cards (responsive container columns)
 * - Persistent layout per user
 * - Same UX as widget dashboard above
 */

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
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
  onHostClick?: (hostId: string) => void
}

// Default layout for host cards (3 columns, each 4 grid units wide)
// Using 36px row height to align with container row height
function generateDefaultLayout(hosts: Host[]): Layout[] {
  return hosts.map((host, index) => ({
    i: host.id,
    x: (index % 3) * 4, // 3 columns: 0, 4, 8
    y: Math.floor(index / 3) * 10, // Stack cards vertically
    w: 4, // Width: 4 units (12/3 = 3 columns)
    h: 10, // Height: 10 units (10 * 36px = 360px default)
    minW: 3, // Minimum 3 units wide
    minH: 6, // Minimum 6 units tall (6 * 36px = 216px minimum - fits header + footer)
  }))
}

export function HostCardsGrid({ hosts, onHostClick }: HostCardsGridProps) {
  const { dashboardPrefs, updateDashboardPrefs, isLoading } = useDashboardPrefs()
  const isInitialMount = useRef(true)

  // Get layout from user prefs or generate default
  const layout = useMemo(() => {
    const storedLayout = dashboardPrefs?.hostCardLayout as Layout[] | undefined

    if (storedLayout && storedLayout.length === hosts.length) {
      // Validate that all IDs in stored layout exist in current hosts
      const hostIds = new Set(hosts.map((h) => h.id))
      const allIdsValid = storedLayout.every((item) => hostIds.has(item.i))

      if (allIdsValid) {
        // Use stored layout - all host IDs match
        return storedLayout
      }

      // Host IDs don't match - hosts were added/removed, regenerate layout
      debug.log('Stored layout invalid (host IDs changed), regenerating default layout')
    }

    // Generate default layout
    return generateDefaultLayout(hosts)
  }, [hosts, dashboardPrefs])

  const [currentLayout, setCurrentLayout] = useState<Layout[]>(layout)

  // Update currentLayout when layout memo changes (e.g., when prefs load)
  useEffect(() => {
    setCurrentLayout(layout)
  }, [layout])

  // Mark initial mount as complete after first render
  useEffect(() => {
    isInitialMount.current = false
  }, [])

  // Handle layout change (drag/resize)
  const handleLayoutChange = useCallback(
    (newLayout: Layout[]) => {
      setCurrentLayout(newLayout)

      // Don't save during initial mount/load (react-grid-layout fires this on mount)
      if (isInitialMount.current) {
        debug.log('Skipping layout save on initial mount')
        return
      }

      // Save to user prefs (debounced via React Query)
      updateDashboardPrefs({
        hostCardLayout: newLayout,
      })

      debug.log('Host cards layout updated:', newLayout)
    },
    [updateDashboardPrefs]
  )

  // Don't render grid until prefs have loaded to prevent flash of default layout
  if (isLoading) {
    return (
      <div className="mt-4">
        <h2 className="text-lg font-semibold mb-4">Hosts</h2>
        <div className="min-h-[400px]" />
      </div>
    )
  }

  return (
    <div className="mt-4">
      <h2 className="text-lg font-semibold mb-4">Hosts</h2>

      <ResponsiveGridLayout
        className="layout"
        layout={currentLayout}
        onLayoutChange={handleLayoutChange}
        cols={12}
        rowHeight={36}
        draggableHandle=".host-card-drag-handle"
        compactType="vertical"
        preventCollision={false}
      >
        {hosts.map((host) => (
          <div key={host.id} className="widget-container">
            {/* Drag handle - positioned to avoid blocking host name and kebab menu */}
            <div className="host-card-drag-handle absolute left-0 top-0 z-10 h-16 cursor-move pointer-events-auto" style={{ width: '40px' }} />

            {/* Host card content */}
            <div className="h-full overflow-hidden relative">
              <ExpandedHostCardContainer
                host={{
                  id: host.id,
                  name: host.name,
                  url: host.url,
                  status: host.status,
                  ...(host.tags && { tags: host.tags }),
                }}
                {...(onHostClick && { onHostClick })}
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
