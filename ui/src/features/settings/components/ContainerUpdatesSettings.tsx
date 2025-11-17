/**
 * Container Updates Settings Component
 * Configure automatic update checks, validation policies, and registry credentials
 */

import { useState, useEffect } from 'react'
import { useGlobalSettings, useUpdateGlobalSettings } from '@/hooks/useSettings'
import { toast } from 'sonner'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api/client'
import { ToggleSwitch } from './ToggleSwitch'
import { UpdatePoliciesSettings } from './UpdatePoliciesSettings'
import { RegistryCredentialsSettings } from './RegistryCredentialsSettings'

export function ContainerUpdatesSettings() {
  const { data: settings } = useGlobalSettings()
  const updateSettings = useUpdateGlobalSettings()

  const [updateCheckTime, setUpdateCheckTime] = useState(settings?.update_check_time ?? '02:00')
  const [skipComposeContainers, setSkipComposeContainers] = useState(settings?.skip_compose_containers ?? true)
  const [healthCheckTimeout, setHealthCheckTimeout] = useState(settings?.health_check_timeout_seconds ?? 120)
  const [isCheckingUpdates, setIsCheckingUpdates] = useState(false)

  // Image pruning settings
  const [pruneImagesEnabled, setPruneImagesEnabled] = useState(settings?.prune_images_enabled ?? true)
  const [imageRetentionCount, setImageRetentionCount] = useState(settings?.image_retention_count ?? 2)
  const [imagePruneGraceHours, setImagePruneGraceHours] = useState(settings?.image_prune_grace_hours ?? 48)
  const [isPruningImages, setIsPruningImages] = useState(false)

  // Sync state when settings load from API
  useEffect(() => {
    if (settings) {
      setUpdateCheckTime(settings.update_check_time ?? '02:00')
      setSkipComposeContainers(settings.skip_compose_containers ?? true)
      setHealthCheckTimeout(settings.health_check_timeout_seconds ?? 120)
      setPruneImagesEnabled(settings.prune_images_enabled ?? true)
      setImageRetentionCount(settings.image_retention_count ?? 2)
      setImagePruneGraceHours(settings.image_prune_grace_hours ?? 48)
    }
  }, [settings])

  const handleUpdateCheckTimeBlur = async () => {
    if (updateCheckTime !== settings?.update_check_time) {
      // Validate time format (HH:MM)
      const timeRegex = /^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$/
      if (!timeRegex.test(updateCheckTime)) {
        toast.error('Invalid time format. Use HH:MM (24-hour format)')
        setUpdateCheckTime(settings?.update_check_time ?? '02:00')
        return
      }

      try {
        await updateSettings.mutateAsync({ update_check_time: updateCheckTime })
        toast.success('Update check time updated')
      } catch (error) {
        toast.error('Failed to update check time')
      }
    }
  }

  const handleSkipComposeToggle = async (checked: boolean) => {
    setSkipComposeContainers(checked)
    try {
      await updateSettings.mutateAsync({ skip_compose_containers: checked })
      toast.success(checked ? 'Compose containers will be skipped' : 'Compose containers will be included')
    } catch (error) {
      toast.error('Failed to update setting')
      setSkipComposeContainers(!checked) // Revert on error
    }
  }

  const handleHealthCheckTimeoutBlur = async () => {
    if (healthCheckTimeout !== settings?.health_check_timeout_seconds) {
      if (healthCheckTimeout < 10 || healthCheckTimeout > 600) {
        toast.error('Timeout must be between 10 and 600 seconds')
        setHealthCheckTimeout(settings?.health_check_timeout_seconds ?? 120)
        return
      }

      try {
        await updateSettings.mutateAsync({ health_check_timeout_seconds: healthCheckTimeout })
        toast.success('Health check timeout updated')
      } catch (error) {
        toast.error('Failed to update timeout')
      }
    }
  }

  const handleCheckAllNow = async () => {
    setIsCheckingUpdates(true)
    try {
      const stats = await apiClient.post<{ total: number; checked: number; updates_found: number; errors: number }>('/updates/check-all', {})

      if (stats.errors > 0) {
        toast.warning(
          `Update check completed with errors. Checked ${stats.checked}/${stats.total} containers, found ${stats.updates_found} updates.`,
          { duration: 5000 }
        )
      } else {
        toast.success(
          `Update check complete! Checked ${stats.checked} containers, found ${stats.updates_found} updates.`,
          { duration: 5000 }
        )
      }
    } catch (error) {
      toast.error(`Failed to check for updates: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsCheckingUpdates(false)
    }
  }

  const handlePruneImagesToggle = async (checked: boolean) => {
    setPruneImagesEnabled(checked)
    try {
      await updateSettings.mutateAsync({ prune_images_enabled: checked })
      toast.success(checked ? 'Image pruning enabled' : 'Image pruning disabled')
    } catch (error) {
      toast.error('Failed to update image pruning setting')
      setPruneImagesEnabled(!checked) // Revert on error
    }
  }

  const handleImageRetentionCountBlur = async () => {
    if (imageRetentionCount !== settings?.image_retention_count) {
      if (imageRetentionCount < 1 || imageRetentionCount > 10) {
        toast.error('Retention count must be between 1 and 10')
        setImageRetentionCount(settings?.image_retention_count ?? 2)
        return
      }

      try {
        await updateSettings.mutateAsync({ image_retention_count: imageRetentionCount })
        toast.success('Image retention count updated')
      } catch (error) {
        toast.error('Failed to update retention count')
        setImageRetentionCount(settings?.image_retention_count ?? 2) // Rollback on error
      }
    }
  }

  const handleImagePruneGraceHoursBlur = async () => {
    if (imagePruneGraceHours !== settings?.image_prune_grace_hours) {
      if (imagePruneGraceHours < 1 || imagePruneGraceHours > 168) {
        toast.error('Grace period must be between 1 and 168 hours')
        setImagePruneGraceHours(settings?.image_prune_grace_hours ?? 48)
        return
      }

      try {
        await updateSettings.mutateAsync({ image_prune_grace_hours: imagePruneGraceHours })
        toast.success('Grace period updated')
      } catch (error) {
        toast.error('Failed to update grace period')
        setImagePruneGraceHours(settings?.image_prune_grace_hours ?? 48) // Rollback on error
      }
    }
  }

  const handlePruneNow = async () => {
    setIsPruningImages(true)
    try {
      const result = await apiClient.post<{ removed: number }>('/images/prune', {})

      if (result.removed > 0) {
        toast.success(`Successfully removed ${result.removed} old/dangling image${result.removed > 1 ? 's' : ''}`, {
          duration: 5000
        })
      } else {
        toast.info('No images to remove (all images are within retention policy)', {
          duration: 5000
        })
      }
    } catch (error) {
      toast.error(`Failed to prune images: ${error instanceof Error ? error.message : 'Unknown error'}`)
    } finally {
      setIsPruningImages(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Update Check Schedule */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Update Check Schedule</h3>
          <p className="text-xs text-gray-400 mt-1">Configure when DockMon checks for container updates</p>
        </div>
        <div className="space-y-4">
          <div>
            <label htmlFor="update-check-time" className="block text-sm font-medium text-gray-300 mb-2">
              Daily Update Check Time
            </label>
            <div className="flex gap-3">
              <input
                id="update-check-time"
                type="time"
                value={updateCheckTime}
                onChange={(e) => setUpdateCheckTime(e.target.value)}
                onBlur={handleUpdateCheckTimeBlur}
                className="flex-1 rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <Button
                onClick={handleCheckAllNow}
                disabled={isCheckingUpdates}
                variant="outline"
                className="whitespace-nowrap"
              >
                <RefreshCw className={`h-4 w-4 mr-2 ${isCheckingUpdates ? 'animate-spin' : ''}`} />
                Check All Now
              </Button>
            </div>
            <p className="mt-1 text-xs text-gray-400">
              Time of day to check for container updates (24-hour format). The system will check for updates once per day at this time.
            </p>
          </div>
        </div>
      </div>

      {/* Update Safety */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Safety Settings</h3>
          <p className="text-xs text-gray-400 mt-1">Configure safety rules for container updates</p>
        </div>
        <div className="space-y-4">
          <div className="divide-y divide-border">
            <ToggleSwitch
              id="skip-compose"
              label="Skip Docker Compose containers"
              description="Automatically skip containers managed by Docker Compose for auto-updates (manual updates still allowed with confirmation)"
              checked={skipComposeContainers}
              onChange={handleSkipComposeToggle}
            />
          </div>

          <div>
            <label htmlFor="health-check-timeout" className="block text-sm font-medium text-gray-300 mb-2">
              Health Check Timeout (seconds)
            </label>
            <input
              id="health-check-timeout"
              type="number"
              min="10"
              max="600"
              value={healthCheckTimeout}
              onChange={(e) => setHealthCheckTimeout(Number(e.target.value))}
              onBlur={handleHealthCheckTimeoutBlur}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
            <p className="mt-1 text-xs text-gray-400">
              Maximum time to wait for health checks after updating a container (10-600 seconds)
            </p>
          </div>
        </div>
      </div>

      {/* Image Cleanup */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Image Cleanup</h3>
          <p className="text-xs text-gray-400 mt-1">Automatically remove unused Docker images to free disk space</p>
        </div>
        <div className="space-y-4">
          <div className="divide-y divide-border">
            <ToggleSwitch
              id="prune-images"
              label="Automatic image pruning"
              description="Automatically remove unused Docker images daily (keeps last N versions per image)"
              checked={pruneImagesEnabled}
              onChange={handlePruneImagesToggle}
            />
          </div>

          {pruneImagesEnabled && (
            <>
              <div>
                <label htmlFor="image-retention-count" className="block text-sm font-medium text-gray-300 mb-2">
                  Image retention count
                </label>
                <input
                  id="image-retention-count"
                  type="number"
                  min="0"
                  max="10"
                  value={imageRetentionCount}
                  onChange={(e) => setImageRetentionCount(Number(e.target.value))}
                  onBlur={handleImageRetentionCountBlur}
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <p className="mt-1 text-xs text-gray-400">
                  Keep last N versions per image. 0 = delete all images except those in use by containers, 1-10 = keep N versions. Older versions removed automatically after grace period.
                </p>
              </div>

              <div>
                <label htmlFor="image-prune-grace-hours" className="block text-sm font-medium text-gray-300 mb-2">
                  Grace period (hours)
                </label>
                <input
                  id="image-prune-grace-hours"
                  type="number"
                  min="1"
                  max="168"
                  value={imagePruneGraceHours}
                  onChange={(e) => setImagePruneGraceHours(Number(e.target.value))}
                  onBlur={handleImagePruneGraceHoursBlur}
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <p className="mt-1 text-xs text-gray-400">
                  Never remove images newer than this (1-168 hours). Provides time for rollback if needed.
                </p>
              </div>
            </>
          )}

          <div>
            <Button
              onClick={handlePruneNow}
              disabled={isPruningImages || !pruneImagesEnabled}
              variant="outline"
              className="w-full"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${isPruningImages ? 'animate-spin' : ''}`} />
              Prune Images Now
            </Button>
            <p className="mt-2 text-xs text-gray-400">
              Manually trigger image cleanup. This will remove unused images based on your retention policy settings.
            </p>
          </div>
        </div>
      </div>

      {/* Update Validation Policies */}
      <div>
        <UpdatePoliciesSettings />
      </div>

      {/* Registry Credentials */}
      <div>
        <RegistryCredentialsSettings />
      </div>
    </div>
  )
}
