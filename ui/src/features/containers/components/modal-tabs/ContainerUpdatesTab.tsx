/**
 * Container Updates Tab
 *
 * Shows update status and allows manual update checks
 * Includes update policy selector and validation
 */

import { memo, useState, useEffect } from 'react'
import { Package, RefreshCw, Check, AlertCircle, Download, Shield, ExternalLink, Edit2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { toast } from 'sonner'
import { useTimeFormat } from '@/lib/hooks/useUserPreferences'
import { formatDateTime } from '@/lib/utils/timeFormat'
import { useContainerUpdateStatus, useCheckContainerUpdate, useUpdateAutoUpdateConfig, useExecuteUpdate } from '../../hooks/useContainerUpdates'
import { useSetContainerUpdatePolicy } from '../../hooks/useUpdatePolicies'
import { UpdateValidationConfirmModal } from '../UpdateValidationConfirmModal'
import { LayerProgressDisplay } from '@/components/shared/LayerProgressDisplay'
import { getRegistryUrl, getRegistryName } from '@/lib/utils/registry'
import type { Container } from '../../types'
import type { UpdatePolicyValue } from '../../types/updatePolicy'
import { POLICY_OPTIONS } from '../../types/updatePolicy'

export interface ContainerUpdatesTabProps {
  container: Container
}

function ContainerUpdatesTabInternal({ container }: ContainerUpdatesTabProps) {
  const { timeFormat } = useTimeFormat()
  // CRITICAL: Always use 12-char short ID for API calls (backend expects short IDs)
  const containerShortId = container.id.slice(0, 12)

  const { data: updateStatus, isLoading, error } = useContainerUpdateStatus(
    container.host_id,
    containerShortId
  )
  const checkUpdate = useCheckContainerUpdate()
  const updateAutoUpdateConfig = useUpdateAutoUpdateConfig()
  const executeUpdate = useExecuteUpdate()
  const setContainerPolicy = useSetContainerUpdatePolicy()

  // Local state for settings
  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(updateStatus?.auto_update_enabled ?? false)
  const [trackingMode, setTrackingMode] = useState<string>(updateStatus?.floating_tag_mode || 'exact')
  const [updatePolicy, setUpdatePolicy] = useState<UpdatePolicyValue>(null)

  // Changelog URL state (v2.0.2+)
  const [changelogUrl, setChangelogUrl] = useState<string>('')
  const [isEditingChangelog, setIsEditingChangelog] = useState(false)

  // Registry page URL state (v2.0.2+)
  const [registryPageUrl, setRegistryPageUrl] = useState<string>('')
  const [isEditingRegistry, setIsEditingRegistry] = useState(false)

  // Update progress state (minimal - just track if updating)
  const [isUpdating, setIsUpdating] = useState(false)

  // Validation confirmation modal state
  const [validationConfirmOpen, setValidationConfirmOpen] = useState(false)
  const [validationReason, setValidationReason] = useState<string>('')
  const [validationPattern, setValidationPattern] = useState<string | undefined>()

  // Rate limiting state for "Check Now" button
  const [lastCheckTime, setLastCheckTime] = useState<number>(0)

  // Sync local state when server data changes
  useEffect(() => {
    if (updateStatus) {
      setAutoUpdateEnabled(updateStatus.auto_update_enabled ?? false)
      setTrackingMode(updateStatus.floating_tag_mode || 'exact')
      setUpdatePolicy(updateStatus.update_policy ?? null)
      setChangelogUrl(updateStatus.changelog_url || '')  // v2.0.2+
      setRegistryPageUrl(updateStatus.registry_page_url || '')  // v2.0.2+
    }
  }, [updateStatus])

  // Log any errors for debugging
  if (error) {
    console.error('Error fetching update status:', error)
  }

  const handleCheckNow = async () => {
    if (!container.host_id) {
      toast.error('Cannot check for updates', {
        description: 'Container missing host information',
      })
      return
    }

    // Rate limiting: prevent spamming "Check Now" button (5 second minimum between checks)
    const now = Date.now()
    const MIN_CHECK_INTERVAL_MS = 5000 // 5 seconds
    if (now - lastCheckTime < MIN_CHECK_INTERVAL_MS) {
      const remainingSeconds = Math.ceil((MIN_CHECK_INTERVAL_MS - (now - lastCheckTime)) / 1000)
      toast.warning(`Please wait ${remainingSeconds} second${remainingSeconds > 1 ? 's' : ''} before checking again`)
      return
    }
    setLastCheckTime(now)

    try {
      await checkUpdate.mutateAsync({
        hostId: container.host_id,
        containerId: containerShortId,
      })
      toast.success('Update check complete')
      // Query will auto-invalidate via the mutation's onSuccess
    } catch (error) {
      toast.error('Failed to check for updates', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  const handleUpdateNow = async () => {
    await performUpdate(false)
  }

  const handleAutoUpdateToggle = async (enabled: boolean) => {
    if (!container.host_id) {
      toast.error('Cannot configure auto-update', {
        description: 'Container missing host information',
      })
      return
    }

    try {
      // Don't update local state optimistically - wait for server response
      const result = await updateAutoUpdateConfig.mutateAsync({
        hostId: container.host_id,
        containerId: containerShortId,
        autoUpdateEnabled: enabled,
        floatingTagMode: trackingMode as 'exact' | 'patch' | 'minor' | 'latest',
      })
      // Update local state only after successful server save
      setAutoUpdateEnabled(result.auto_update_enabled ?? false)
      toast.success(enabled ? 'Auto-update enabled' : 'Auto-update disabled')
    } catch (error) {
      // No need to revert - we never changed it optimistically
      toast.error('Failed to update configuration', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  const handleTrackingModeChange = async (mode: string) => {
    if (!container.host_id) {
      toast.error('Cannot configure tracking mode', {
        description: 'Container missing host information',
      })
      return
    }

    try {
      // Don't update local state optimistically - wait for server response
      const result = await updateAutoUpdateConfig.mutateAsync({
        hostId: container.host_id,
        containerId: containerShortId,
        autoUpdateEnabled,
        floatingTagMode: mode as 'exact' | 'patch' | 'minor' | 'latest',
      })
      // Update local state only after successful server save
      setTrackingMode(result.floating_tag_mode || 'exact')
      toast.success('Tracking mode updated')
    } catch (error) {
      // No need to revert - we never changed it optimistically
      toast.error('Failed to update tracking mode', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  const handlePolicyChange = async (policy: UpdatePolicyValue) => {
    if (!container.host_id) {
      toast.error('Cannot configure update policy', {
        description: 'Container missing host information',
      })
      return
    }

    try {
      // Don't update local state optimistically - wait for server response
      const result = await setContainerPolicy.mutateAsync({
        hostId: container.host_id,
        containerId: containerShortId,
        policy,
      })
      // Update local state only after successful server save
      setUpdatePolicy(result.update_policy ?? null)
      const policyLabel = POLICY_OPTIONS.find((opt) => opt.value === policy)?.label || 'Auto-detect'
      toast.success(`Update policy set to ${policyLabel}`)
    } catch (error) {
      // No need to revert - we never changed it optimistically
      toast.error('Failed to update policy', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  const handleChangelogSave = async () => {
    if (!container.host_id) {
      toast.error('Cannot save changelog URL', {
        description: 'Container missing host information',
      })
      return
    }

    // Validate URL format if not empty
    if (changelogUrl.trim()) {
      try {
        new URL(changelogUrl.trim())
      } catch {
        toast.error('Invalid URL format', {
          description: 'Please enter a valid URL (e.g., https://github.com/user/repo/releases)',
        })
        return
      }
    }

    try {
      // Don't update local state optimistically - wait for server response
      const result = await updateAutoUpdateConfig.mutateAsync({
        hostId: container.host_id,
        containerId: containerShortId,
        autoUpdateEnabled,
        floatingTagMode: trackingMode as 'exact' | 'patch' | 'minor' | 'latest',
        changelogUrl: changelogUrl.trim() || null,  // v2.0.2+
      })
      // Update local state only after successful server save
      setChangelogUrl(result.changelog_url || '')
      toast.success(changelogUrl.trim() ? 'Changelog URL saved' : 'Changelog URL cleared')
      setIsEditingChangelog(false)
    } catch (error) {
      // No need to revert - we never changed it optimistically
      toast.error('Failed to save changelog URL', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  const handleRegistrySave = async () => {
    if (!container.host_id) {
      toast.error('Cannot save registry URL', {
        description: 'Container missing host information',
      })
      return
    }

    // Validate URL format if not empty
    if (registryPageUrl.trim()) {
      try {
        new URL(registryPageUrl.trim())
      } catch {
        toast.error('Invalid URL format', {
          description: 'Please enter a valid URL (e.g., https://hub.docker.com/r/user/image)',
        })
        return
      }
    }

    try {
      // Don't update local state optimistically - wait for server response
      const result = await updateAutoUpdateConfig.mutateAsync({
        hostId: container.host_id,
        containerId: containerShortId,
        autoUpdateEnabled,
        floatingTagMode: trackingMode as 'exact' | 'patch' | 'minor' | 'latest',
        registryPageUrl: registryPageUrl.trim() || null,  // v2.0.2+
      })
      // Update local state only after successful server save
      setRegistryPageUrl(result.registry_page_url || '')
      toast.success(registryPageUrl.trim() ? 'Registry URL saved' : 'Registry URL cleared')
      setIsEditingRegistry(false)
    } catch (error) {
      // No need to revert - we never changed it optimistically
      toast.error('Failed to save registry URL', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  const handleConfirmUpdate = async () => {
    // User confirmed, proceed with update
    await performUpdate(true)
  }

  const performUpdate = async (force: boolean = false) => {
    if (!container.host_id) {
      toast.error('Cannot execute update', {
        description: 'Container missing host information',
      })
      return
    }

    // Mark as updating (progress will be tracked by LayerProgressDisplay)
    setIsUpdating(true)

    try {
      const result = await executeUpdate.mutateAsync({
        hostId: container.host_id,
        containerId: containerShortId,
        force,
      })

      // Check if update is blocked by policy
      if (result.status === 'blocked' || result.validation === 'block') {
        setIsUpdating(false)
        toast.error('Update blocked by policy', {
          description: result.reason || 'This container has a block policy that prevents updates',
        })
        return
      }

      // Check if validation warning returned
      if (!force && result.validation === 'warn') {
        setValidationReason(result.reason || 'Container matched validation pattern')
        setValidationPattern(result.matched_pattern)
        setValidationConfirmOpen(true)
        setIsUpdating(false)
        return
      }

      // Check if update failed (e.g., health check timeout, startup issues)
      if (result.status === 'failed') {
        setIsUpdating(false)
        toast.error(result.message || 'Container update failed', {
          description: result.detail || 'The update failed and your container has been automatically restored to its previous state.',
          duration: 10000, // Longer duration for important failure message
        })
        return
      }

      toast.success('Container updated successfully', {
        description: result.message,
      })
      setIsUpdating(false)
      // Query will auto-invalidate via the mutation's onSuccess
    } catch (error) {
      setIsUpdating(false)
      toast.error('Failed to update container', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const hasUpdate = updateStatus?.update_available
  const lastChecked = updateStatus?.last_checked_at
    ? formatDateTime(updateStatus.last_checked_at, timeFormat)
    : 'Not Checked'

  // Check if auto-updates are enabled but won't work due to blockers
  const isComposeBlocked = updateStatus?.is_compose_container && updateStatus?.skip_compose_enabled
  const isValidationBlocked = updateStatus?.validation_info?.result === 'block'
  const isValidationWarned = updateStatus?.validation_info?.result === 'warn'

  const hasBlockers = autoUpdateEnabled && (isComposeBlocked || isValidationBlocked || isValidationWarned)

  return (
    <div className="p-6 space-y-6">
      {/* Header with status */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {hasUpdate ? (
            <>
              <Package className="h-8 w-8 text-amber-500" />
              <div>
                <h3 className="text-lg font-semibold text-amber-500">Update Available</h3>
                <p className="text-sm text-muted-foreground">
                  A newer version of this container image is available
                </p>
              </div>
            </>
          ) : (
            <>
              <Check className="h-8 w-8 text-success" />
              <div>
                <h3 className="text-lg font-semibold">Up to Date</h3>
                <p className="text-sm text-muted-foreground">
                  This container is running the latest available image
                </p>
              </div>
            </>
          )}
        </div>

        <div className="flex flex-col items-end gap-2">
          <div className="flex gap-2">
            {hasUpdate && (
              <Button
                onClick={handleUpdateNow}
                disabled={executeUpdate.isPending}
                variant="default"
              >
                {executeUpdate.isPending ? (
                  <>
                    <Download className="mr-2 h-4 w-4 animate-spin" />
                    Updating...
                  </>
                ) : (
                  <>
                    <Download className="mr-2 h-4 w-4" />
                    Update Now
                  </>
                )}
              </Button>
            )}
            <Button
              onClick={handleCheckNow}
              disabled={checkUpdate.isPending}
              variant="outline"
            >
              {checkUpdate.isPending ? (
                <>
                  <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                  Checking...
                </>
              ) : (
                <>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Check Now
                </>
              )}
            </Button>
          </div>
          {updateStatus && (
            <p className="text-xs text-muted-foreground">
              Last checked: {lastChecked}
            </p>
          )}
        </div>
      </div>

      {/* Auto-Update Blocker Warning */}
      {hasBlockers && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-yellow-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="text-sm font-semibold text-yellow-200 mb-2">
                Auto-Update Won't Run Automatically
              </h4>
              <p className="text-sm text-yellow-200/90 mb-3">
                Despite enabling auto-updates, this container won't update automatically because:
              </p>
              <ul className="text-sm text-yellow-200/90 space-y-1.5">
                {isComposeBlocked && (
                  <li className="flex flex-col gap-1">
                    <span>• This container uses Docker Compose which is blocked by system settings</span>
                    <span className="text-xs text-yellow-200/70 ml-4">
                      Change in Settings → Container Updates → "Skip Docker Compose containers"
                    </span>
                  </li>
                )}
                {isValidationBlocked && updateStatus?.validation_info && (
                  <li className="flex flex-col gap-1">
                    <span>• {updateStatus.validation_info.reason}</span>
                    <span className="text-xs text-yellow-200/70 ml-4">
                      {updateStatus.validation_info.matched_pattern
                        ? `Change in Settings → Update Validation → Edit pattern "${updateStatus.validation_info.matched_pattern}"`
                        : 'Change in Settings → Update Validation or update the container policy'
                      }
                    </span>
                  </li>
                )}
                {isValidationWarned && updateStatus?.validation_info && (
                  <li className="flex flex-col gap-1">
                    <span>• Requires manual confirmation: {updateStatus.validation_info.reason}</span>
                    <span className="text-xs text-yellow-200/70 ml-4">
                      {updateStatus.validation_info.matched_pattern
                        ? `Matched pattern "${updateStatus.validation_info.matched_pattern}" - confirmation required for each update`
                        : 'Manual confirmation required for each update'
                      }
                    </span>
                  </li>
                )}
              </ul>
              <p className="text-xs text-yellow-200/70 mt-3">
                Manual updates are still available using the "Update Now" button above.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Update Progress - Using shared LayerProgressDisplay component */}
      {isUpdating && container.host_id && (
        <LayerProgressDisplay
          hostId={container.host_id}
          entityId={containerShortId}
          eventType="container_update_layer_progress"
          simpleProgressEventType="container_update_progress"
          initialProgress={0}
          initialMessage="Initializing update..."
        />
      )}

      {/* Update details */}
      <div className="grid grid-cols-2 gap-6">
        {/* Current Image */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-4 w-4 text-muted-foreground" />
            <h4 className="text-sm font-medium text-muted-foreground">Current Image</h4>
          </div>
          <div className="bg-muted rounded-lg p-4 space-y-2">
            <div>
              <p className="text-xs text-muted-foreground">Image</p>
              <p className="text-sm font-mono break-all">
                {updateStatus?.current_image || container.image}
              </p>
            </div>
            {updateStatus?.current_version && (
              <div>
                <p className="text-xs text-muted-foreground">Version</p>
                <p className="text-sm font-semibold">{updateStatus.current_version}</p>
              </div>
            )}
            {updateStatus?.current_digest && (
              <div>
                <p className="text-xs text-muted-foreground">Digest</p>
                <p className="text-sm font-mono text-xs">{updateStatus.current_digest}</p>
              </div>
            )}
          </div>
        </div>

        {/* Latest Image */}
        {hasUpdate && updateStatus && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Package className="h-4 w-4 text-amber-500" />
              <h4 className="text-sm font-medium text-amber-500">Latest Available</h4>
            </div>
            <div className="bg-muted rounded-lg p-4 space-y-2">
              <div>
                <p className="text-xs text-muted-foreground">Image</p>
                <p className="text-sm font-mono break-all">{updateStatus.latest_image}</p>
              </div>
              {updateStatus.latest_version && (
                <div>
                  <p className="text-xs text-muted-foreground">Version</p>
                  <p className="text-sm font-semibold text-amber-500">{updateStatus.latest_version}</p>
                </div>
              )}
              {updateStatus.latest_digest && (
                <div>
                  <p className="text-xs text-muted-foreground">Digest</p>
                  <p className="text-sm font-mono text-xs">{updateStatus.latest_digest}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Changelog & Registry Links (v2.0.2+) */}
      <div className="border-t pt-6">
        <h4 className="text-lg font-medium text-foreground mb-4">Resource Links</h4>

        <div className="grid grid-cols-2 gap-6">
          {/* Changelog URL */}
          <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium">Changelog</label>
            {updateStatus?.changelog_source === 'manual' && (
              <span className="text-xs text-blue-400 px-2 py-0.5 bg-blue-400/10 rounded">Manual</span>
            )}
            {updateStatus?.changelog_source && updateStatus.changelog_source !== 'manual' && updateStatus.changelog_source !== 'failed' && (
              <span className="text-xs text-blue-400 px-2 py-0.5 bg-blue-400/10 rounded">Auto-detected</span>
            )}
          </div>

          {isEditingChangelog ? (
            <div className="flex gap-2">
              <Input
                value={changelogUrl}
                onChange={(e) => setChangelogUrl(e.target.value)}
                placeholder="https://github.com/user/repo/releases"
                className="flex-1"
              />
              <Button onClick={handleChangelogSave} size="sm" disabled={updateAutoUpdateConfig.isPending}>
                {updateAutoUpdateConfig.isPending ? 'Saving...' : 'Save'}
              </Button>
              <Button onClick={() => {
                setChangelogUrl(updateStatus?.changelog_url || '')
                setIsEditingChangelog(false)
              }} size="sm" variant="outline">
                <X className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <div className="flex gap-2">
              {changelogUrl ? (
                <a
                  href={changelogUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex-1 flex items-center gap-2 text-sm text-blue-500 hover:text-blue-600 bg-muted rounded-lg p-3 transition-colors"
                >
                  <ExternalLink className="h-4 w-4 flex-shrink-0" />
                  <span className="truncate">{changelogUrl}</span>
                </a>
              ) : (
                <div className="flex-1 text-sm text-muted-foreground bg-muted rounded-lg p-3">
                  No changelog URL configured
                </div>
              )}
              <Button
                onClick={() => setIsEditingChangelog(true)}
                size="sm"
                variant="outline"
                className="flex-shrink-0"
              >
                <Edit2 className="h-4 w-4 mr-1" />
                {changelogUrl ? 'Edit' : 'Add'}
              </Button>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {updateStatus?.changelog_source === 'manual'
              ? 'Manual URLs are preserved and not overwritten by auto-detection. Clear to re-enable auto-detection.'
              : 'Auto-detected changelog links can be overridden with a custom URL.'}
          </p>
        </div>

          {/* Docker Registry Link */}
          <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium">Docker Registry</label>
            {updateStatus?.registry_page_source === 'manual' && (
              <span className="text-xs text-blue-400 px-2 py-0.5 bg-blue-400/10 rounded">Manual</span>
            )}
            {!updateStatus?.registry_page_source && (
              <span className="text-xs text-blue-400 px-2 py-0.5 bg-blue-400/10 rounded">Auto-detected</span>
            )}
          </div>

          {isEditingRegistry ? (
            <div className="flex gap-2">
              <Input
                value={registryPageUrl}
                onChange={(e) => setRegistryPageUrl(e.target.value)}
                placeholder="https://hub.docker.com/r/user/image"
                className="flex-1"
              />
              <Button onClick={handleRegistrySave} size="sm" disabled={updateAutoUpdateConfig.isPending}>
                {updateAutoUpdateConfig.isPending ? 'Saving...' : 'Save'}
              </Button>
              <Button onClick={() => {
                setRegistryPageUrl(updateStatus?.registry_page_url || '')
                setIsEditingRegistry(false)
              }} size="sm" variant="outline">
                <X className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <div className="flex gap-2">
              {/* Use manual URL if set, otherwise auto-detect */}
              {(() => {
                const displayUrl = registryPageUrl || getRegistryUrl(container.image)
                const displayName = registryPageUrl ? 'View Registry' : `View on ${getRegistryName(container.image)}`
                return (
                  <a
                    href={displayUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-1 flex items-center gap-2 text-sm text-blue-500 hover:text-blue-600 bg-muted rounded-lg p-3 transition-colors"
                  >
                    <ExternalLink className="h-4 w-4 flex-shrink-0" />
                    <span className="truncate">{displayName}</span>
                  </a>
                )
              })()}
              <Button
                onClick={() => setIsEditingRegistry(true)}
                size="sm"
                variant="outline"
                className="flex-shrink-0"
              >
                <Edit2 className="h-4 w-4 mr-1" />
                {registryPageUrl ? 'Edit' : 'Add'}
              </Button>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {updateStatus?.registry_page_source === 'manual'
              ? 'Manual URLs are preserved and not overwritten by auto-detection. Clear to re-enable auto-detection.'
              : 'Auto-detected registry links can be overridden with a custom URL.'}
          </p>
          </div>
        </div>
      </div>

      {/* Settings */}
      <div className="space-y-4 border-t pt-6">
        <h4 className="text-lg font-medium text-foreground mb-3">Update Settings</h4>

        <div className="space-y-4">
          {/* Auto-update toggle */}
          <div className="flex items-start justify-between py-4">
            <div className="flex-1 mr-4">
              <label htmlFor="auto-update" className="text-sm font-medium cursor-pointer">
                Auto-update
              </label>
              <p className="text-sm text-muted-foreground mt-1">
                Automatically update this container when new versions are available
              </p>
            </div>
            <Switch
              id="auto-update"
              checked={autoUpdateEnabled}
              onCheckedChange={handleAutoUpdateToggle}
              disabled={updateAutoUpdateConfig.isPending}
            />
          </div>

          {/* Tracking mode selector */}
          <div className="py-4">
            <div className="mb-3">
              <label className="text-sm font-medium">
                Tracking Mode
              </label>
              <p className="text-sm text-muted-foreground mt-1">
                Choose how DockMon should track updates for this container
              </p>
            </div>

            <div className="space-y-3">
              {/* Respect Tag (was "exact") */}
              <label
                className={`flex items-start gap-3 p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  trackingMode === 'exact'
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:border-primary/50'
                } ${updateAutoUpdateConfig.isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <input
                  type="radio"
                  name="tracking-mode"
                  value="exact"
                  checked={trackingMode === 'exact'}
                  onChange={(e) => handleTrackingModeChange(e.target.value)}
                  disabled={updateAutoUpdateConfig.isPending}
                  className="mt-0.5 h-4 w-4 text-primary"
                />
                <div className="flex-1">
                  <div className="font-medium text-sm">Respect Tag</div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Use the image tag defined in your container or Compose configuration. If the tag is fixed (e.g., nginx:1.25.3),
                    the container will stay on that version. If it's a floating tag (e.g., :latest), DockMon will pull the newest
                    image for that tag.
                  </p>
                </div>
              </label>

              {/* Patch Updates */}
              <label
                className={`flex items-start gap-3 p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  trackingMode === 'patch'
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:border-primary/50'
                } ${updateAutoUpdateConfig.isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <input
                  type="radio"
                  name="tracking-mode"
                  value="patch"
                  checked={trackingMode === 'patch'}
                  onChange={(e) => handleTrackingModeChange(e.target.value)}
                  disabled={updateAutoUpdateConfig.isPending}
                  className="mt-0.5 h-4 w-4 text-primary"
                />
                <div className="flex-1">
                  <div className="font-medium text-sm">Patch Updates</div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Track patch updates only (bug fixes). Example: nginx:1.25.3 → tracks 1.25.x
                    (will detect 1.25.4, 1.25.99, but not 1.26.0). Most conservative option.
                  </p>
                </div>
              </label>

              {/* Minor Updates */}
              <label
                className={`flex items-start gap-3 p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  trackingMode === 'minor'
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:border-primary/50'
                } ${updateAutoUpdateConfig.isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <input
                  type="radio"
                  name="tracking-mode"
                  value="minor"
                  checked={trackingMode === 'minor'}
                  onChange={(e) => handleTrackingModeChange(e.target.value)}
                  disabled={updateAutoUpdateConfig.isPending}
                  className="mt-0.5 h-4 w-4 text-primary"
                />
                <div className="flex-1">
                  <div className="font-medium text-sm">Minor Updates</div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Track minor and patch updates within the same major version. Example: nginx:1.25.3 → tracks 1.x
                    (will detect 1.26.0, 1.99.0, but not 2.0.0). Recommended for most users.
                  </p>
                </div>
              </label>

              {/* Always Latest */}
              <label
                className={`flex items-start gap-3 p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  trackingMode === 'latest'
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:border-primary/50'
                } ${updateAutoUpdateConfig.isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <input
                  type="radio"
                  name="tracking-mode"
                  value="latest"
                  checked={trackingMode === 'latest'}
                  onChange={(e) => handleTrackingModeChange(e.target.value)}
                  disabled={updateAutoUpdateConfig.isPending}
                  className="mt-0.5 h-4 w-4 text-primary"
                />
                <div className="flex-1">
                  <div className="font-medium text-sm">Always Latest</div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Always track the :latest tag regardless of your current version. This will pull the newest available
                    version, which may include breaking changes.
                  </p>
                </div>
              </label>
            </div>
          </div>

          {/* Update policy selector */}
          <div className="flex items-start justify-between py-4 border-t">
            <div className="flex-1 mr-4">
              <label htmlFor="update-policy" className="text-sm font-medium flex items-center gap-2">
                <Shield className="h-4 w-4" />
                Update Policy
              </label>
              <p className="text-sm text-muted-foreground mt-1">
                Control when this container can be updated
              </p>
            </div>
            <Select
              value={updatePolicy ?? 'null'}
              onValueChange={(value) => handlePolicyChange(value === 'null' ? null : value as UpdatePolicyValue)}
              disabled={setContainerPolicy.isPending}
            >
              <SelectTrigger id="update-policy" className="w-[180px]">
                <SelectValue>
                  {POLICY_OPTIONS.find((opt) => opt.value === updatePolicy)?.label || 'Use Global Settings'}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {POLICY_OPTIONS.map((option) => (
                  <SelectItem key={option.value ?? 'null'} value={option.value ?? 'null'}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* Validation Confirmation Modal */}
      <UpdateValidationConfirmModal
        isOpen={validationConfirmOpen}
        onClose={() => setValidationConfirmOpen(false)}
        onConfirm={handleConfirmUpdate}
        containerName={container.name}
        reason={validationReason}
        matchedPattern={validationPattern}
      />

      {/* Help text */}
      <div className="bg-muted/50 rounded-lg p-4 text-sm text-muted-foreground space-y-2">
        <p className="font-medium">About Container Updates</p>
        <ul className="list-disc list-inside space-y-1 text-xs">
          <li>DockMon checks for updates daily at the configured time</li>
          <li>Click "Check Now" to manually check for updates immediately</li>
          <li>Auto-update will automatically pull and recreate containers when updates are available</li>
          <li>Container health is verified after updates to ensure successful deployment</li>
          <li>Updates are detected by comparing image digests, not just tags</li>
          <li>For Compose-managed containers, updates apply to the running container only. Update your compose file to persist changes</li>
        </ul>
      </div>
    </div>
  )
}

// Memoize component to prevent unnecessary re-renders
// Return true if props are equal (should NOT re-render)
export const ContainerUpdatesTab = memo(ContainerUpdatesTabInternal, (prevProps, nextProps) => {
  // Only re-render if container ID or host ID changes
  const areEqual = (
    prevProps.container.id === nextProps.container.id &&
    prevProps.container.host_id === nextProps.container.host_id
  )
  return areEqual
})
