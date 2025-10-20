/**
 * System Settings Component
 * Polling, retries, timeouts, and connection settings
 */

import { useState, useEffect } from 'react'
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
  const [unusedTagRetentionDays, setUnusedTagRetentionDays] = useState(settings?.unused_tag_retention_days ?? 30)
  const [eventRetentionDays, setEventRetentionDays] = useState(settings?.event_retention_days ?? 60)
  const [alertRetentionDays, setAlertRetentionDays] = useState(settings?.alert_retention_days ?? 90)

  // Sync state when settings load from API
  useEffect(() => {
    if (settings) {
      setPollingInterval(settings.polling_interval ?? 2)
      setConnectionTimeout(settings.connection_timeout ?? 10)
      setMaxRetries(settings.max_retries ?? 3)
      setRetryDelay(settings.retry_delay ?? 30)
      setDefaultAutoRestart(settings.default_auto_restart ?? false)
      setUnusedTagRetentionDays(settings.unused_tag_retention_days ?? 30)
      setEventRetentionDays(settings.event_retention_days ?? 60)
      setAlertRetentionDays(settings.alert_retention_days ?? 90)
    }
  }, [settings])

  // Auto-save handlers for number inputs (save on blur)
  const handlePollingIntervalBlur = async () => {
    if (pollingInterval !== settings?.polling_interval) {
      try {
        await updateSettings.mutateAsync({ polling_interval: pollingInterval })
        toast.success('Polling interval updated')
      } catch (error) {
        toast.error('Failed to update polling interval')
      }
    }
  }

  const handleConnectionTimeoutBlur = async () => {
    if (connectionTimeout !== settings?.connection_timeout) {
      try {
        await updateSettings.mutateAsync({ connection_timeout: connectionTimeout })
        toast.success('Connection timeout updated')
      } catch (error) {
        toast.error('Failed to update connection timeout')
      }
    }
  }

  const handleMaxRetriesBlur = async () => {
    if (maxRetries !== settings?.max_retries) {
      try {
        await updateSettings.mutateAsync({ max_retries: maxRetries })
        toast.success('Max retries updated')
      } catch (error) {
        toast.error('Failed to update max retries')
      }
    }
  }

  const handleRetryDelayBlur = async () => {
    if (retryDelay !== settings?.retry_delay) {
      try {
        await updateSettings.mutateAsync({ retry_delay: retryDelay })
        toast.success('Retry delay updated')
      } catch (error) {
        toast.error('Failed to update retry delay')
      }
    }
  }

  const handleUnusedTagRetentionBlur = async () => {
    if (unusedTagRetentionDays !== settings?.unused_tag_retention_days) {
      try {
        await updateSettings.mutateAsync({ unused_tag_retention_days: unusedTagRetentionDays })
        toast.success('Tag retention updated')
      } catch (error) {
        toast.error('Failed to update tag retention')
      }
    }
  }

  const handleEventRetentionBlur = async () => {
    if (eventRetentionDays !== settings?.event_retention_days) {
      try {
        await updateSettings.mutateAsync({ event_retention_days: eventRetentionDays })
        toast.success('Event retention updated')
      } catch (error) {
        toast.error('Failed to update event retention')
      }
    }
  }

  const handleAlertRetentionBlur = async () => {
    if (alertRetentionDays !== settings?.alert_retention_days) {
      try {
        await updateSettings.mutateAsync({ alert_retention_days: alertRetentionDays })
        toast.success('Alert retention updated')
      } catch (error) {
        toast.error('Failed to update alert retention')
      }
    }
  }

  // Auto-save handler for toggle
  const handleDefaultAutoRestartToggle = async (checked: boolean) => {
    setDefaultAutoRestart(checked)
    try {
      await updateSettings.mutateAsync({ default_auto_restart: checked })
      toast.success(checked ? 'Auto-restart enabled by default' : 'Auto-restart disabled by default')
    } catch (error) {
      toast.error('Failed to update auto-restart setting')
      setDefaultAutoRestart(!checked) // Revert on error
    }
  }

  return (
    <div className="space-y-6">
      {/* Monitoring */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Monitoring</h3>
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
              onBlur={handlePollingIntervalBlur}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">How often to check Docker hosts (1-300 seconds)</p>
          </div>
        </div>
      </div>

      {/* Connection */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Connection</h3>
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
              onBlur={handleConnectionTimeoutBlur}
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
              onBlur={handleMaxRetriesBlur}
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
              onBlur={handleRetryDelayBlur}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">Delay between retry attempts (5-300 seconds)</p>
          </div>
        </div>
      </div>

      {/* Container Behavior */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Container Behavior</h3>
          <p className="text-xs text-gray-400 mt-1">Default behavior for containers</p>
        </div>
        <div className="divide-y divide-border">
          <ToggleSwitch
            id="default-auto-restart"
            label="Auto-restart containers by default"
            description="Automatically restart containers that stop unexpectedly (can be overridden per container)"
            checked={defaultAutoRestart}
            onChange={handleDefaultAutoRestartToggle}
          />
        </div>
      </div>

      {/* Data Retention */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Data Retention</h3>
          <p className="text-xs text-gray-400 mt-1">Configure how long DockMon keeps historical data</p>
        </div>
        <div className="space-y-4">
          <div>
            <label htmlFor="event-retention" className="block text-sm font-medium text-gray-300 mb-2">
              Event Retention (days)
            </label>
            <input
              id="event-retention"
              type="number"
              min="0"
              max="365"
              value={eventRetentionDays}
              onChange={(e) => setEventRetentionDays(Number(e.target.value))}
              onBlur={handleEventRetentionBlur}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">
              How long to keep event logs and history. Events older than this are automatically deleted during nightly maintenance. Set to 0 to keep events forever. (0-365 days)
            </p>
          </div>

          <div>
            <label htmlFor="unused-tag-retention" className="block text-sm font-medium text-gray-300 mb-2">
              Unused Tag Retention (days)
            </label>
            <input
              id="unused-tag-retention"
              type="number"
              min="0"
              max="365"
              value={unusedTagRetentionDays}
              onChange={(e) => setUnusedTagRetentionDays(Number(e.target.value))}
              onBlur={handleUnusedTagRetentionBlur}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">
              Automatically delete tags that haven't been assigned to anything for this many days. Set to 0 to keep unused tags forever. (0-365 days)
            </p>
          </div>

          <div>
            <label htmlFor="alert-retention" className="block text-sm font-medium text-gray-300 mb-2">
              Alert Retention (days)
            </label>
            <input
              id="alert-retention"
              type="number"
              min="0"
              max="365"
              value={alertRetentionDays}
              onChange={(e) => setAlertRetentionDays(Number(e.target.value))}
              onBlur={handleAlertRetentionBlur}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">
              How long to keep resolved alerts. Resolved alerts older than this are automatically deleted during nightly maintenance. Set to 0 to keep alerts forever. (0-365 days)
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
