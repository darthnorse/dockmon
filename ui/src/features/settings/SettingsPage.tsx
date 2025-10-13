/**
 * Settings Page
 * User preferences and configuration
 */

import { useState } from 'react'
import { DashboardSettings } from './components/DashboardSettings'
import { AlertNotificationSettings } from './components/AlertNotificationSettings'

type Tab = 'dashboard' | 'alerts'

export function SettingsPage() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard')

  return (
    <div className="flex h-full flex-col bg-[#0a0e14]">
      {/* Header */}
      <div className="border-b border-gray-800 bg-[#0d1117] px-6 py-4">
        <h1 className="text-xl font-semibold text-white">Settings</h1>
        <p className="text-sm text-gray-400">Manage your preferences and configuration</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-800 bg-[#0d1117] px-6">
        <div className="flex gap-6">
          <button
            onClick={() => setActiveTab('dashboard')}
            className={`relative py-3 text-sm font-medium transition-colors ${
              activeTab === 'dashboard'
                ? 'text-blue-400'
                : 'text-gray-400 hover:text-gray-300'
            }`}
          >
            Dashboard
            {activeTab === 'dashboard' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-400" />
            )}
          </button>
          <button
            onClick={() => setActiveTab('alerts')}
            className={`relative py-3 text-sm font-medium transition-colors ${
              activeTab === 'alerts'
                ? 'text-blue-400'
                : 'text-gray-400 hover:text-gray-300'
            }`}
          >
            Alerts & Notifications
            {activeTab === 'alerts' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-blue-400" />
            )}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        <div className="container mx-auto px-6 py-6 max-w-4xl">
          {activeTab === 'dashboard' && <DashboardSettings />}
          {activeTab === 'alerts' && <AlertNotificationSettings />}
        </div>
      </div>
    </div>
  )
}
