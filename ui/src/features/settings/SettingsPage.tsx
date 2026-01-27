/**
 * Settings Page
 * User preferences and configuration
 */

import { useState, useMemo } from 'react'
import { LayoutDashboard, Bell, AlertTriangle, Settings, Package, Key, ScrollText, Users, LucideIcon, KeyRound, Shield, UserSquare2, ClipboardList } from 'lucide-react'
import { DashboardSettings } from './components/DashboardSettings'
import { NotificationChannelsSection } from './components/NotificationChannelsSection'
import { AlertTemplateSettings } from './components/AlertTemplateSettings'
import { BlackoutWindowsSection } from './components/BlackoutWindowsSection'
import { SystemSettings } from './components/SystemSettings'
import { ContainerUpdatesSettings } from './components/ContainerUpdatesSettings'
import { ApiKeysSettings } from './components/ApiKeysSettings'
import { EventsSettings } from './components/EventsSettings'
import { UsersSettings } from './components/UsersSettings'
import { OIDCSettings } from './components/OIDCSettings'
import { GroupsSettings } from './components/GroupsSettings'
import { GroupPermissionsSettings } from './components/GroupPermissionsSettings'
import { AuditLogSettings } from './components/AuditLogSettings'
import { useAuth } from '@/features/auth/AuthContext'

type TabId = 'dashboard' | 'alerts' | 'notifications' | 'updates' | 'events' | 'api-keys' | 'users' | 'groups' | 'permissions' | 'oidc' | 'audit-log' | 'system'

interface Tab {
  id: TabId
  label: string
  icon: LucideIcon
  // Capabilities required to see this tab (any of these grants access)
  capabilities?: string[]
}

const TABS: Tab[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'alerts', label: 'Alerts', icon: AlertTriangle, capabilities: ['alerts.view', 'alerts.manage'] },
  { id: 'notifications', label: 'Notifications', icon: Bell, capabilities: ['notifications.view', 'notifications.manage'] },
  { id: 'updates', label: 'Container Updates', icon: Package, capabilities: ['policies.view', 'policies.manage'] },
  { id: 'events', label: 'Events', icon: ScrollText, capabilities: ['events.view'] },
  { id: 'api-keys', label: 'API Keys', icon: Key, capabilities: ['apikeys.manage_own', 'apikeys.manage_other'] },
  { id: 'users', label: 'Users', icon: Users, capabilities: ['users.manage'] },
  { id: 'groups', label: 'Groups', icon: UserSquare2, capabilities: ['groups.manage'] },
  { id: 'permissions', label: 'Permissions', icon: Shield, capabilities: ['groups.manage'] },
  { id: 'oidc', label: 'OIDC', icon: KeyRound, capabilities: ['oidc.manage'] },
  { id: 'audit-log', label: 'Audit Log', icon: ClipboardList, capabilities: ['audit.view'] },
  { id: 'system', label: 'System', icon: Settings, capabilities: ['settings.manage'] },
]

export function SettingsPage() {
  const { hasCapability } = useAuth()
  const [activeTab, setActiveTab] = useState<TabId>('dashboard')

  // Filter tabs based on user capabilities
  const visibleTabs = useMemo(
    () => TABS.filter((tab) => {
      // No capabilities required = visible to all
      if (!tab.capabilities || tab.capabilities.length === 0) return true
      // User has at least one of the required capabilities
      return tab.capabilities.some((cap) => hasCapability(cap))
    }),
    [hasCapability]
  )

  return (
    <div className="flex h-full flex-col bg-[#0a0e14]">
      {/* Header */}
      <div className="border-b border-gray-800 bg-[#0d1117] px-3 sm:px-4 md:px-6 py-4 mt-12 md:mt-0">
        <h1 className="text-xl sm:text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">Manage your preferences and configuration</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-800 bg-[#0d1117]">
        <div className="flex gap-1 px-3 sm:px-4 md:px-6 overflow-x-auto">
          {visibleTabs.map((tab) => {
            const Icon = tab.icon
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                  isActive
                    ? 'border-blue-500 text-blue-500'
                    : 'border-transparent text-gray-400 hover:text-gray-300'
                }`}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        <div className="container mx-auto max-w-4xl px-3 sm:px-4 md:px-6 py-4 sm:py-6">
          {activeTab === 'dashboard' && <DashboardSettings />}
          {activeTab === 'alerts' && (hasCapability('alerts.view') || hasCapability('alerts.manage')) && (
            <div className="space-y-8">
              <div>
                <h2 className="mb-4 text-lg font-semibold text-white">Blackout Windows</h2>
                <BlackoutWindowsSection />
              </div>
              <div>
                <h2 className="mb-4 text-lg font-semibold text-white">Alert Message Templates</h2>
                <AlertTemplateSettings />
              </div>
            </div>
          )}
          {activeTab === 'notifications' && (hasCapability('notifications.view') || hasCapability('notifications.manage')) && <NotificationChannelsSection />}
          {activeTab === 'updates' && (hasCapability('policies.view') || hasCapability('policies.manage')) && <ContainerUpdatesSettings />}
          {activeTab === 'events' && hasCapability('events.view') && <EventsSettings />}
          {activeTab === 'api-keys' && (hasCapability('apikeys.manage_own') || hasCapability('apikeys.manage_other')) && <ApiKeysSettings />}
          {activeTab === 'users' && hasCapability('users.manage') && <UsersSettings />}
          {activeTab === 'groups' && hasCapability('groups.manage') && <GroupsSettings />}
          {activeTab === 'permissions' && hasCapability('groups.manage') && <GroupPermissionsSettings />}
          {activeTab === 'oidc' && hasCapability('oidc.manage') && <OIDCSettings />}
          {activeTab === 'audit-log' && hasCapability('audit.view') && <AuditLogSettings />}
          {activeTab === 'system' && hasCapability('settings.manage') && <SystemSettings />}
        </div>
      </div>
    </div>
  )
}
