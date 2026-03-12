/**
 * Dashboard Widget Types - Phase 3b
 *
 * Widget system for drag-and-drop dashboard layout
 * Uses react-grid-layout for positioning
 */

export type WidgetType =
  | 'container-stats'
  | 'host-stats'
  | 'recent-events'
  | 'alert-summary'
  | 'updates'

export interface WidgetConfig {
  id: string
  type: WidgetType
  title: string
  // react-grid-layout position
  x: number
  y: number
  w: number
  h: number
  minW?: number
  minH?: number
  maxW?: number
  maxH?: number
}

export interface DashboardLayout {
  widgets: WidgetConfig[]
}

/**
 * Compact host shape used by compact dashboard cards.
 *
 * Status is `string` (not a narrow union) because the API can return
 * values like 'degraded' that compact cards handle via a default case.
 */
export interface CompactHost {
  id: string
  name: string
  url: string
  status: string
  tags?: string[]
}
