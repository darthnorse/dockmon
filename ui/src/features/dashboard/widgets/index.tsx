/**
 * Widget Registry
 *
 * Maps widget types to their components
 * Allows dynamic widget rendering based on configuration
 */

import type { WidgetType } from '../types'
import { ContainerStatsWidget } from './ContainerStatsWidget'
import { HostStatsWidget } from './HostStatsWidget'
import { RecentEventsWidget } from './RecentEventsWidget'
import { AlertSummaryWidget } from './AlertSummaryWidget'
import { UpdatesWidget } from './UpdatesWidget'

export const widgetComponents: Record<WidgetType, React.ComponentType> = {
  'container-stats': ContainerStatsWidget,
  'host-stats': HostStatsWidget,
  'recent-events': RecentEventsWidget,
  'alert-summary': AlertSummaryWidget,
  'updates': UpdatesWidget,
}

export * from './ContainerStatsWidget'
export * from './HostStatsWidget'
export * from './RecentEventsWidget'
export * from './AlertSummaryWidget'
export * from './UpdatesWidget'
