/**
 * Settings Page
 * User preferences and configuration
 */

import { useState } from 'react'
import { LayoutDashboard, Bell, AlertTriangle, Settings, Package, Key, ScrollText, LucideIcon } from 'lucide-react'
import { DashboardSettings } from './components/DashboardSettings'
import { NotificationChannelsSection } from './components/NotificationChannelsSection'
import { AlertTemplateSettings } from './components/AlertTemplateSettings'
import { BlackoutWindowsSection } from './components/BlackoutWindowsSection'
import { SystemSettings } from './components/SystemSettings'
import { ContainerUpdatesSettings } from './components/ContainerUpdatesSettings'
import { ApiKeysSettings } from './components/ApiKeysSettings'
import { EventsSettings } from './components/EventsSettings'

type TabId = 'dashboard' | 'alerts' | 'notifications' | 'updates' | 'events' | 'api-keys' | 'system'

interface Tab {
  id: TabId
  label: string
  icon: LucideIcon
}

const TABS: Tab[] = [
  { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { id: 'alerts', label: 'Alerts', icon: AlertTriangle },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'updates', label: 'Container Updates', icon: Package },
  { id: 'events', label: 'Events', icon: ScrollText },
  { id: 'api-keys', label: 'API Keys', icon: Key },
  { id: 'system', label: 'System', icon: Settings },
]

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<TabId>('dashboard')

  return (
    <div className="flex h-full flex-col bg-[#0a0e14]">
      {/* Header */}
      <div className="border-b border-gray-800 bg-[#0d1117] px-6 py-4">
        <h1 className="text-2xl font-bold text-white">Settings</h1>
        <p className="text-sm text-gray-400 mt-1">Manage your preferences and configuration</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-800 bg-[#0d1117]">
        <div className="flex gap-1 px-6">
          {TABS.map((tab) => {
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
        <div className="container mx-auto max-w-4xl px-6 py-6">
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
          {activeTab === 'system' && <SystemSettings />}
        </div>
      </div>
    </div>
  )
}
