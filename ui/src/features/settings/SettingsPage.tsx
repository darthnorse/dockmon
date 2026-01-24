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
import { RolesSettings } from './components/RolesSettings'
import { GroupsSettings } from './components/GroupsSettings'
import { AuditLogSettings } from './components/AuditLogSettings'
import { useAuth } from '@/features/auth/AuthContext'

type TabId = 'dashboard' | 'alerts' | 'notifications' | 'updates' | 'events' | 'api-keys' | 'users' | 'roles' | 'groups' | 'oidc' | 'audit-log' | 'system'

interface Tab {
  id: TabId
  label: string
  icon: LucideIcon
  adminOnly?: boolean
}

const TABS: Tab[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'alerts', label: 'Alerts', icon: AlertTriangle },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'updates', label: 'Container Updates', icon: Package },
  { id: 'events', label: 'Events', icon: ScrollText },
  { id: 'api-keys', label: 'API Keys', icon: Key },
  { id: 'users', label: 'Users', icon: Users, adminOnly: true },
  { id: 'roles', label: 'Roles', icon: Shield, adminOnly: true },
  { id: 'groups', label: 'Groups', icon: UserSquare2, adminOnly: true },
  { id: 'oidc', label: 'OIDC', icon: KeyRound, adminOnly: true },
  { id: 'audit-log', label: 'Audit Log', icon: ClipboardList, adminOnly: true },
  { id: 'system', label: 'System', icon: Settings },
]

export function SettingsPage() {
  const { isAdmin } = useAuth()
  const [activeTab, setActiveTab] = useState<TabId>('dashboard')

  // Filter tabs based on user role
  const visibleTabs = useMemo(
    () => TABS.filter((tab) => !tab.adminOnly || isAdmin),
    [isAdmin]
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
          {activeTab === 'alerts' && (
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
          {activeTab === 'notifications' && <NotificationChannelsSection />}
          {activeTab === 'updates' && <ContainerUpdatesSettings />}
          {activeTab === 'events' && <EventsSettings />}
          {activeTab === 'api-keys' && <ApiKeysSettings />}
          {activeTab === 'users' && isAdmin && <UsersSettings />}
          {activeTab === 'roles' && isAdmin && <RolesSettings />}
          {activeTab === 'groups' && isAdmin && <GroupsSettings />}
          {activeTab === 'oidc' && isAdmin && <OIDCSettings />}
          {activeTab === 'audit-log' && isAdmin && <AuditLogSettings />}
          {activeTab === 'system' && <SystemSettings />}
        </div>
      </div>
    </div>
  )
}
