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
import { Button } from '@/components/ui/button'
import { RotateCcw } from 'lucide-react'
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
    console.log('🔄 GridDashboard: savedLayout changed:', savedLayout)
    if (savedLayout?.widgets) {
      console.log('🔄 GridDashboard: Loading layout from database:', savedLayout.widgets)
      debug.log('GridDashboard', 'Loading layout from database')
      setWidgets(savedLayout.widgets)
    } else {
      console.log('🔄 GridDashboard: No saved layout found, using default')
    }
  }, [savedLayout])

  // Persist layout changes (debounced to avoid excessive API calls)
  const handleLayoutChange = useCallback((newLayout: Layout[]) => {
    console.log('🔍 GridDashboard: handleLayoutChange called with:', newLayout)

    // Use functional update to avoid stale closure
    setWidgets((currentWidgets) => {
      console.log('🔍 GridDashboard: Current widgets:', currentWidgets)

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

      console.log('🔍 GridDashboard: Updated widgets:', updatedWidgets)

      // Debounce save to database (1 second after last change)
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current)
      }

      saveTimerRef.current = setTimeout(() => {
        console.log('💾 GridDashboard: Saving layout to database')
        debug.log('GridDashboard', 'Saving layout to database')
        const dashboardLayout: DashboardLayout = { widgets: updatedWidgets }
        console.log('💾 GridDashboard: Dashboard layout to save:', dashboardLayout)
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

  // Reset to default layout
  const handleReset = () => {
    debug.log('GridDashboard', 'Resetting layout to defaults')
    setWidgets(defaultLayout)
    const dashboardLayout: DashboardLayout = { widgets: defaultLayout }
    setLayout(dashboardLayout)
  }

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
    <div className="p-6 min-w-[900px] overflow-x-auto">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Monitor your Docker containers and hosts
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={handleReset}>
          <RotateCcw className="mr-2 h-4 w-4" />
          Reset Layout
        </Button>
      </div>

      {/* Grid Layout - Responsive width with 900px minimum */}
      <ResponsiveGridLayout
        className="layout"
        layout={layout}
        cols={12}
        rowHeight={120}
        onLayoutChange={handleLayoutChange}
        onDragStart={(_layout, oldItem, newItem) => {
          console.log('🎯 GridDashboard: Drag started', { oldItem, newItem })
        }}
        onDrag={(_layout, oldItem, newItem) => {
          console.log('🎯 GridDashboard: Dragging', { oldItem, newItem })
        }}
        onDragStop={(_layout, oldItem, newItem) => {
          console.log('🎯 GridDashboard: Drag stopped', { oldItem, newItem })
        }}
        draggableHandle=".widget-drag-handle"
        compactType="vertical"
        preventCollision={false}
      >
        {widgets.map((widget) => {
          const WidgetComponent = widgetComponents[widget.type]

          return (
            <div key={widget.id} className="widget-container relative">
              {/* Drag handle (invisible but functional) */}
              <div
                className="widget-drag-handle absolute inset-x-0 top-0 z-10 h-12 cursor-move"
                onMouseDown={() => console.log('🖱️ Mouse down on drag handle:', widget.id)}
              />

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
