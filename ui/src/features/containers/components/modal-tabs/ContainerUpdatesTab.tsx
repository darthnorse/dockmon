/**
 * Container Updates Tab
 *
 * Shows update status and allows manual update checks
 * Includes update policy selector and validation
 */

import { memo, useState, useEffect, useCallback } from 'react'
import { Package, RefreshCw, Check, Clock, AlertCircle, Download, Shield } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { toast } from 'sonner'
import { useContainerUpdateStatus, useCheckContainerUpdate, useUpdateAutoUpdateConfig, useExecuteUpdate } from '../../hooks/useContainerUpdates'
import { useSetContainerUpdatePolicy } from '../../hooks/useUpdatePolicies'
import { UpdateValidationConfirmModal } from '../UpdateValidationConfirmModal'
import { useWebSocketContext } from '@/lib/websocket/WebSocketProvider'
import type { Container } from '../../types'
import type { UpdatePolicyValue } from '../../types/updatePolicy'
import { POLICY_OPTIONS } from '../../types/updatePolicy'

interface UpdateProgress {
  stage: string
  progress: number
  message: string
}

export interface ContainerUpdatesTabProps {
  container: Container
}

function ContainerUpdatesTabInternal({ container }: ContainerUpdatesTabProps) {
  const { data: updateStatus, isLoading, error } = useContainerUpdateStatus(
    container.host_id,
    container.id
  )
  const checkUpdate = useCheckContainerUpdate()
  const updateAutoUpdateConfig = useUpdateAutoUpdateConfig()
  const executeUpdate = useExecuteUpdate()
  const setContainerPolicy = useSetContainerUpdatePolicy()
  const { addMessageHandler } = useWebSocketContext()

  // Local state for settings
  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(updateStatus?.auto_update_enabled ?? false)
  const [trackingMode, setTrackingMode] = useState<string>(updateStatus?.floating_tag_mode || 'exact')
  const [updatePolicy, setUpdatePolicy] = useState<UpdatePolicyValue>(null)

  // Update progress state
  const [updateProgress, setUpdateProgress] = useState<UpdateProgress | null>(null)

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
    }
  }, [updateStatus])

  // Listen for update progress messages via WebSocket
  const handleProgressMessage = useCallback(
    (message: any) => {
      if (
        message.type === 'container_update_progress' &&
        message.data?.host_id === container.host_id &&
        message.data?.container_id === container.id
      ) {
        setUpdateProgress({
          stage: message.data.stage,
          progress: message.data.progress,
          message: message.data.message,
        })

        // Clear progress when update completes
        if (message.data.stage === 'completed') {
          setTimeout(() => setUpdateProgress(null), 3000)
        }
      }
    },
    [container.host_id, container.id]
  )

  useEffect(() => {
    const cleanup = addMessageHandler(handleProgressMessage)
    return cleanup
  }, [addMessageHandler, handleProgressMessage])

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
        containerId: container.id,
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
      setAutoUpdateEnabled(enabled)
      await updateAutoUpdateConfig.mutateAsync({
        hostId: container.host_id,
        containerId: container.id,
        autoUpdateEnabled: enabled,
        floatingTagMode: trackingMode as 'exact' | 'minor' | 'major' | 'latest',
      })
      toast.success(enabled ? 'Auto-update enabled' : 'Auto-update disabled')
    } catch (error) {
      // Revert on error
      setAutoUpdateEnabled(!enabled)
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

    const previousMode = trackingMode

    try {
      setTrackingMode(mode)
      await updateAutoUpdateConfig.mutateAsync({
        hostId: container.host_id,
        containerId: container.id,
        autoUpdateEnabled,
        floatingTagMode: mode as 'exact' | 'minor' | 'major' | 'latest',
      })
      toast.success('Tracking mode updated')
    } catch (error) {
      // Revert on error
      setTrackingMode(previousMode)
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

    const previousPolicy = updatePolicy

    try {
      setUpdatePolicy(policy)
      await setContainerPolicy.mutateAsync({
        hostId: container.host_id,
        containerId: container.id,
        policy,
      })
      const policyLabel = POLICY_OPTIONS.find((opt) => opt.value === policy)?.label || 'Auto-detect'
      toast.success(`Update policy set to ${policyLabel}`)
    } catch (error) {
      // Revert on error
      setUpdatePolicy(previousPolicy)
      toast.error('Failed to update policy', {
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

    // Reset progress state before starting
    setUpdateProgress({ stage: 'starting', progress: 0, message: 'Initializing update...' })

    try {
      const result = await executeUpdate.mutateAsync({
        hostId: container.host_id,
        containerId: container.id,
        force,
      })

      // Check if validation warning returned
      if (!force && result.validation === 'warn') {
        setValidationReason(result.reason || 'Container matched validation pattern')
        setValidationPattern(result.matched_pattern)
        setValidationConfirmOpen(true)
        setUpdateProgress(null)
        return
      }

      toast.success('Container updated successfully', {
        description: result.message,
      })
      // Query will auto-invalidate via the mutation's onSuccess
    } catch (error) {
      setUpdateProgress(null) // Clear progress on error
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
    ? new Date(updateStatus.last_checked_at).toLocaleString()
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

      {/* Update Progress */}
      {updateProgress && (
        <div className="space-y-3 rounded-lg border border-blue-500/50 bg-blue-500/10 p-4">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium text-blue-400">{updateProgress.message}</span>
            <span className="text-blue-400">{updateProgress.progress}%</span>
          </div>
          <div className="relative h-2 w-full overflow-hidden rounded-full bg-blue-950">
            <div
              className="h-full bg-blue-500 transition-all duration-500 ease-out"
              style={{ width: `${updateProgress.progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Status Details */}
      {updateStatus && (
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-muted rounded-lg p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <Clock className="h-4 w-4" />
              <span className="text-xs font-medium">Last Checked</span>
            </div>
            <p className="text-sm font-medium">{lastChecked}</p>
          </div>

          {updateStatus.current_digest && (
            <div className="bg-muted rounded-lg p-4">
              <div className="flex items-center gap-2 text-muted-foreground mb-1">
                <AlertCircle className="h-4 w-4" />
                <span className="text-xs font-medium">Current Digest</span>
              </div>
              <p className="text-sm font-mono font-medium">{updateStatus.current_digest}</p>
            </div>
          )}

          {hasUpdate && updateStatus.latest_digest && (
            <div className="bg-amber-500/10 rounded-lg p-4">
              <div className="flex items-center gap-2 text-amber-500 mb-1">
                <Package className="h-4 w-4" />
                <span className="text-xs font-medium">Latest Digest</span>
              </div>
              <p className="text-sm font-mono font-medium text-amber-500">{updateStatus.latest_digest}</p>
            </div>
          )}
        </div>
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
            {updateStatus?.current_digest && (
              <div>
                <p className="text-xs text-muted-foreground">Digest</p>
                <p className="text-sm font-mono">{updateStatus.current_digest}</p>
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
              {updateStatus.latest_digest && (
                <div>
                  <p className="text-xs text-muted-foreground">Digest</p>
                  <p className="text-sm font-mono">{updateStatus.latest_digest}</p>
                </div>
              )}
            </div>
          </div>
        )}
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
                  <div className="font-medium text-sm">Minor Updates (X.Y.z)</div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Track patch updates within the same minor version. Example: nginx:1.25.3 → tracks 1.25.x
                    (will detect 1.25.4, 1.25.5, but not 1.26.0 or 2.0.0)
                  </p>
                </div>
              </label>

              {/* Major Updates */}
              <label
                className={`flex items-start gap-3 p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  trackingMode === 'major'
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:border-primary/50'
                } ${updateAutoUpdateConfig.isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <input
                  type="radio"
                  name="tracking-mode"
                  value="major"
                  checked={trackingMode === 'major'}
                  onChange={(e) => handleTrackingModeChange(e.target.value)}
                  disabled={updateAutoUpdateConfig.isPending}
                  className="mt-0.5 h-4 w-4 text-primary"
                />
                <div className="flex-1">
                  <div className="font-medium text-sm">Major Updates (X.y.z)</div>
                  <p className="text-xs text-muted-foreground mt-1">
                    Track all updates within the same major version. Example: nginx:1.25.3 → tracks 1.x
                    (will detect 1.26.0, 1.99.0, but not 2.0.0)
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
