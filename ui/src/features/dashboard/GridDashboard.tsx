/**
 * Grid Dashboard Component - Phase 3b
 *
 * FEATURES:
 * - Drag-and-drop widget layout (react-grid-layout)
 * - Persistent layout (database - syncs across devices)
 * - Responsive grid (12 columns)
 * - Real-time data updates via TanStack Query
 *
 * ARCHITECTURE:
 * - Layout state persisted to database via API
 * - Widgets registered in widgetComponents registry
 * - Grid automatically adjusts on resize
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import GridLayout, { WidthProvider, type Layout } from 'react-grid-layout'
import type { WidgetConfig, DashboardLayout } from './types'
import { widgetComponents } from './widgets'
import { useDashboardLayout } from '@/lib/hooks/useUserPreferences'
import { debug } from '@/lib/debug'
import 'react-grid-layout/css/styles.css'

// Responsive grid that auto-adjusts width
const ResponsiveGridLayout = WidthProvider(GridLayout)

// Default dashboard layout (Hosts → Containers → Updates → Events → Alerts)
// Phase 4: Added Updates widget
// Grid is 12 columns: 3 small widgets (2 cols) + 2 large widgets (3 cols) = 12
const defaultLayout: WidgetConfig[] = [
  {
    id: 'host-stats',
    type: 'host-stats',
    title: 'Host Stats',
    x: 0,
    y: 0,
    w: 2,
    h: 2,
    minW: 2,
    minH: 2,
  },
  {
    id: 'container-stats',
    type: 'container-stats',
    title: 'Container Stats',
    x: 2,
    y: 0,
    w: 2,
    h: 2,
    minW: 2,
    minH: 2,
  },
  {
    id: 'updates',
    type: 'updates',
    title: 'Updates',
    x: 4,
    y: 0,
    w: 2,
    h: 2,
    minW: 2,
    minH: 2,
  },
  {
    id: 'recent-events',
    type: 'recent-events',
    title: 'Recent Events',
    x: 6,
    y: 0,
    w: 3,
    h: 2,
    minW: 3,
    minH: 2,
  },
  {
    id: 'alert-summary',
    type: 'alert-summary',
    title: 'Active Alerts',
    x: 9,
    y: 0,
    w: 3,
    h: 2,
    minW: 3,
    minH: 2,
  },
]

export function GridDashboard() {
  const { layout: savedLayout, setLayout } = useDashboardLayout()
  const [widgets, setWidgets] = useState<WidgetConfig[]>(defaultLayout)

  // Debounce timer for saving layout changes
  const saveTimerRef = useRef<NodeJS.Timeout>()

  // Load layout from database on mount
  useEffect(() => {
    if (savedLayout?.widgets) {
      debug.log('GridDashboard', 'Loading layout from database')
      setWidgets(savedLayout.widgets)
    }
  }, [savedLayout])

  // Persist layout changes (debounced to avoid excessive API calls)
  const handleLayoutChange = useCallback((newLayout: Layout[]) => {
    // Use functional update to avoid stale closure
    setWidgets((currentWidgets) => {
      const updatedWidgets = currentWidgets.map((widget) => {
        const layoutItem = newLayout.find((l) => l.i === widget.id)
        if (layoutItem) {
          return {
            ...widget,
            x: layoutItem.x,
            y: layoutItem.y,
            w: layoutItem.w,
            h: layoutItem.h,
          }
        }
        return widget
      })

      // Debounce save to database (1 second after last change)
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current)
      }

      saveTimerRef.current = setTimeout(() => {
        debug.log('GridDashboard', 'Saving layout to database')
        const dashboardLayout: DashboardLayout = { widgets: updatedWidgets }
        setLayout(dashboardLayout)
      }, 1000)

      return updatedWidgets
    })
  }, [setLayout])

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current)
      }
    }
  }, [])

  // Convert widgets to react-grid-layout format (memoized for performance)
  const layout: Layout[] = useMemo(
    () =>
      widgets.map((w) => ({
        i: w.id,
        x: w.x,
        y: w.y,
        w: w.w,
        h: w.h,
        minW: w.minW,
        minH: w.minH,
        maxW: w.maxW,
        maxH: w.maxH,
      })),
    [widgets]
  )

  return (
    <div className="w-full">
      {/* Grid Layout - Responsive width */}
      <ResponsiveGridLayout
        className="layout"
        layout={layout}
        cols={12}
        rowHeight={120}
        onLayoutChange={handleLayoutChange}
        draggableHandle=".widget-drag-handle"
        compactType="vertical"
        preventCollision={false}
        style={{ width: '100%' }}
      >
        {widgets.map((widget) => {
          const WidgetComponent = widgetComponents[widget.type]

          return (
            <div key={widget.id} className="widget-container relative">
              {/* Drag handle (invisible but functional) */}
              <div className="widget-drag-handle absolute inset-x-0 top-0 z-10 h-12 cursor-move" />

              {/* Widget content */}
              <div className="h-full">
                <WidgetComponent />
              </div>
            </div>
          )
        })}
      </ResponsiveGridLayout>
    </div>
  )
}
