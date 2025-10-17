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
