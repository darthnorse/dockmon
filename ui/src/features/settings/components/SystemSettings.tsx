/**
 * System Settings Component
 * Polling, retries, timeouts, and connection settings
 */

import { useState } from 'react'
import { useGlobalSettings, useUpdateGlobalSettings } from '@/hooks/useSettings'
import { toast } from 'sonner'
import { ToggleSwitch } from './ToggleSwitch'

export function SystemSettings() {
  const { data: settings } = useGlobalSettings()
  const updateSettings = useUpdateGlobalSettings()

  const [pollingInterval, setPollingInterval] = useState(settings?.polling_interval ?? 2)
  const [connectionTimeout, setConnectionTimeout] = useState(settings?.connection_timeout ?? 10)
  const [maxRetries, setMaxRetries] = useState(settings?.max_retries ?? 3)
  const [retryDelay, setRetryDelay] = useState(settings?.retry_delay ?? 30)
  const [defaultAutoRestart, setDefaultAutoRestart] = useState(settings?.default_auto_restart ?? false)

  const handleSave = async () => {
    try {
      await updateSettings.mutateAsync({
        polling_interval: pollingInterval,
        connection_timeout: connectionTimeout,
        max_retries: maxRetries,
        retry_delay: retryDelay,
        default_auto_restart: defaultAutoRestart,
      })
      toast.success('System settings saved')
    } catch (error) {
      toast.error('Failed to save system settings')
    }
  }

  const hasChanges =
    pollingInterval !== settings?.polling_interval ||
    connectionTimeout !== settings?.connection_timeout ||
    maxRetries !== settings?.max_retries ||
    retryDelay !== settings?.retry_delay ||
    defaultAutoRestart !== settings?.default_auto_restart

  return (
    <div className="space-y-6">
      {/* Monitoring */}
      <div>
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-white">Monitoring</h3>
          <p className="text-xs text-gray-400 mt-1">Configure how frequently DockMon checks your Docker hosts</p>
        </div>
        <div className="space-y-4">
          <div>
            <label htmlFor="polling-interval" className="block text-sm font-medium text-gray-300 mb-2">
              Polling Interval (seconds)
            </label>
            <input
              id="polling-interval"
              type="number"
              min="1"
              max="300"
              value={pollingInterval}
              onChange={(e) => setPollingInterval(Number(e.target.value))}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">How often to check Docker hosts (1-300 seconds)</p>
          </div>
        </div>
      </div>

      {/* Connection */}
      <div>
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-white">Connection</h3>
          <p className="text-xs text-gray-400 mt-1">Connection timeout and retry settings</p>
        </div>
        <div className="space-y-4">
          <div>
            <label htmlFor="connection-timeout" className="block text-sm font-medium text-gray-300 mb-2">
              Connection Timeout (seconds)
            </label>
            <input
              id="connection-timeout"
              type="number"
              min="1"
              max="60"
              value={connectionTimeout}
              onChange={(e) => setConnectionTimeout(Number(e.target.value))}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">Timeout for Docker API connections (1-60 seconds)</p>
          </div>

          <div>
            <label htmlFor="max-retries" className="block text-sm font-medium text-gray-300 mb-2">
              Max Retries
            </label>
            <input
              id="max-retries"
              type="number"
              min="0"
              max="10"
              value={maxRetries}
              onChange={(e) => setMaxRetries(Number(e.target.value))}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">Number of retry attempts for failed connections (0-10)</p>
          </div>

          <div>
            <label htmlFor="retry-delay" className="block text-sm font-medium text-gray-300 mb-2">
              Retry Delay (seconds)
            </label>
            <input
              id="retry-delay"
              type="number"
              min="5"
              max="300"
              value={retryDelay}
              onChange={(e) => setRetryDelay(Number(e.target.value))}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">Delay between retry attempts (5-300 seconds)</p>
          </div>
        </div>
      </div>

      {/* Container Behavior */}
      <div>
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-white">Container Behavior</h3>
          <p className="text-xs text-gray-400 mt-1">Default behavior for containers</p>
        </div>
        <div className="divide-y divide-border">
          <ToggleSwitch
            id="default-auto-restart"
            label="Auto-restart containers by default"
            description="Automatically restart containers that stop unexpectedly (can be overridden per container)"
            checked={defaultAutoRestart}
            onChange={setDefaultAutoRestart}
          />
        </div>
      </div>

      {/* Save Button */}
      {hasChanges && (
        <div className="flex items-center justify-end gap-3 rounded-lg border border-blue-500/20 bg-blue-500/10 px-4 py-3">
          <span className="text-sm text-gray-300">You have unsaved changes</span>
          <button
            onClick={handleSave}
            disabled={updateSettings.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            {updateSettings.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      )}
    </div>
  )
}
