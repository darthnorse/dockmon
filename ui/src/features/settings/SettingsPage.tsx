/**
 * Settings Page
 * User preferences and configuration
 */

import { DashboardSettings } from './components/DashboardSettings'

export function SettingsPage() {
  return (
    <div className="container mx-auto px-4 py-6 max-w-4xl">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <div className="space-y-6">
        <DashboardSettings />
      </div>
    </div>
  )
}
