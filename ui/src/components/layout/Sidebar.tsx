/**
 * Sidebar Navigation - Design System v2
 *
 * FEATURES:
 * - Collapsible (240px → 72px)
 * - Active state with accent bar
 * - Portainer/Grafana-inspired design
 * - Responsive (auto-collapse on mobile)
 * - Accessible (keyboard navigation, ARIA labels)
 *
 * ARCHITECTURE:
 * - State persisted to database (syncs across devices)
 * - NavLink for active route detection
 * - Icon-only mode with tooltips
 */

import { useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Container,
  Layers,
  Server,
  Activity,
  Bell,
  Settings,
  FileText,
  ChevronLeft,
  ChevronRight,
  X,
  Wifi,
  WifiOff,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import { useSidebarCollapsed } from '@/lib/hooks/useUserPreferences'
import { UserMenu } from './UserMenu'
import { DockMonUpdateBanner } from './DockMonUpdateBanner'
import { AgentUpdateBanner } from './AgentUpdateBanner'

interface NavItem {
  label: string
  icon: LucideIcon
  path: string
  badge?: number
}

const navigationItems: NavItem[] = [
  { label: 'Dashboard', icon: LayoutDashboard, path: '/' },
  { label: 'Hosts', icon: Server, path: '/hosts' },
  { label: 'Containers', icon: Container, path: '/containers' },
  { label: 'Stacks', icon: Layers, path: '/stacks' },
  { label: 'Container Logs', icon: FileText, path: '/logs' },
  { label: 'Events', icon: Activity, path: '/events' },
  { label: 'Alerts', icon: Bell, path: '/alerts' },
  { label: 'Settings', icon: Settings, path: '/settings' },
]

interface SidebarProps {
  isMobileMenuOpen?: boolean
  onMobileClose?: () => void
}

export function Sidebar({ isMobileMenuOpen = false, onMobileClose }: SidebarProps) {
  const { status: wsStatus } = useWebSocketContext()
  const { isCollapsed, setCollapsed } = useSidebarCollapsed()

  // Notify AppLayout when collapsed state changes (for layout adjustments)
  useEffect(() => {
    window.dispatchEvent(new Event('sidebar-toggle'))
  }, [isCollapsed])

  // Auto-collapse on mobile
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 1024 && !isCollapsed) {
        setCollapsed(true)
      }
    }

    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [isCollapsed, setCollapsed])

  return (
    <aside
      className={cn(
        'fixed left-0 top-0 h-screen border-r border-border bg-surface-1 transition-all duration-300',
        // Mobile: always full width (w-60), Desktop: responsive to collapsed state
        'w-60 md:w-auto',
        isCollapsed ? 'md:w-18' : 'md:w-60',
        // Mobile: overlay that slides in from left
        'z-50 md:z-40',
        'md:translate-x-0',
        isMobileMenuOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
      )}
      aria-label="Main navigation"
    >
      {/* Logo / Header */}
      <div className="flex h-16 items-center justify-between border-b border-border px-4">
        {/* Mobile: always show full logo, Desktop: conditional */}
        <div className="flex items-center gap-2 md:hidden">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Container className="h-5 w-5 text-primary" />
          </div>
          <span className="text-lg font-semibold">DockMon</span>
        </div>

        {/* Desktop logo (conditional on collapsed state) */}
        {!isCollapsed && (
          <div className="hidden md:flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
              <Container className="h-5 w-5 text-primary" />
            </div>
            <span className="text-lg font-semibold">DockMon</span>
          </div>
        )}
        {isCollapsed && (
          <div className="hidden md:flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Container className="h-5 w-5 text-primary" />
          </div>
        )}

        {/* Toggle Button - X on mobile, chevron on desktop */}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => {
            // Mobile: close the menu, Desktop: toggle collapsed
            if (window.innerWidth < 768) {
              onMobileClose?.()
            } else {
              setCollapsed(!isCollapsed)
            }
          }}
          className={cn('h-8 w-8', isCollapsed && 'md:mx-auto')}
          aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {/* Mobile: X icon, Desktop: chevrons */}
          <X className="h-4 w-4 md:hidden" />
          {isCollapsed ? (
            <ChevronRight className="h-4 w-4 hidden md:block" />
          ) : (
            <ChevronLeft className="h-4 w-4 hidden md:block" />
          )}
        </Button>
      </div>

      {/* Navigation Items */}
      <nav className="flex flex-col gap-1 p-3" role="navigation">
        {navigationItems.map((item) => {
          const Icon = item.icon

          return (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={() => onMobileClose?.()}
              data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, '-')}`}
              className={({ isActive }) =>
                cn(
                  'group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
                  'hover:bg-surface-2 hover:text-foreground',
                  isActive
                    ? 'bg-surface-2 text-foreground before:absolute before:left-0 before:top-0 before:h-full before:w-0.5 before:rounded-r before:bg-primary'
                    : 'text-muted-foreground'
                )
              }
              title={isCollapsed ? item.label : undefined}
            >
              <Icon className="h-5 w-5 flex-shrink-0" />
              {/* Mobile: always show labels, Desktop: conditional on collapsed state */}
              <span className="md:hidden">{item.label}</span>
              {!isCollapsed && <span className="hidden md:inline">{item.label}</span>}
              {!isCollapsed && item.badge && item.badge > 0 && (
                <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-danger px-1.5 text-xs font-semibold text-white">
                  {item.badge > 99 ? '99+' : item.badge}
                </span>
              )}
            </NavLink>
          )
        })}
      </nav>

      {/* User Info + WebSocket Status (bottom) */}
      <div
        className={cn(
          'absolute bottom-0 left-0 right-0 border-t border-border bg-surface-1 p-3',
          isCollapsed && 'md:px-2'
        )}
      >
        {/* Agent Update Notification */}
        <AgentUpdateBanner isCollapsed={isCollapsed} />

        {/* DockMon Update Notification */}
        <DockMonUpdateBanner isCollapsed={isCollapsed} />

        {/* WebSocket Status */}
        <div
          className={cn(
            'mb-2 flex items-center gap-2 rounded-lg px-2 py-1.5',
            isCollapsed && 'md:justify-center'
          )}
          title={`WebSocket: ${wsStatus}`}
        >
          {wsStatus === 'connected' ? (
            <Wifi className="h-3.5 w-3.5 text-success" />
          ) : (
            <WifiOff className="h-3.5 w-3.5 text-muted-foreground" />
          )}
          {/* Mobile: always show, Desktop: conditional on collapsed state */}
          <span className="text-xs text-muted-foreground md:hidden">
            {wsStatus === 'connected' ? 'Real-time updates' : 'Reconnecting...'}
          </span>
          {!isCollapsed && (
            <span className="hidden md:inline text-xs text-muted-foreground">
              {wsStatus === 'connected' ? 'Real-time updates' : 'Reconnecting...'}
            </span>
          )}
        </div>

        {/* User Menu */}
        <UserMenu isCollapsed={isCollapsed} />
      </div>
    </aside>
  )
}
