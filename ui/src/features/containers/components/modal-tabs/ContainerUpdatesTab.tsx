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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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
          <div className="flex items-start justify-between py-4">
            <div className="flex-1 mr-4">
              <label htmlFor="tracking-mode" className="text-sm font-medium">
                Tracking Mode
              </label>
              <p className="text-sm text-muted-foreground mt-1">
                How to track updates for this container
              </p>
            </div>
            <Select
              value={trackingMode}
              onValueChange={handleTrackingModeChange}
              disabled={updateAutoUpdateConfig.isPending}
            >
              <SelectTrigger id="tracking-mode" className="w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="exact">Exact Tag</SelectItem>
                <SelectItem value="minor">Minor (x.Y.z)</SelectItem>
                <SelectItem value="major">Major (X.y.z)</SelectItem>
                <SelectItem value="latest">Latest</SelectItem>
              </SelectContent>
            </Select>
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
              <SelectTrigger id="update-policy" className="w-[160px]">
                <SelectValue />
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
          <li>Tracking modes: exact (specific tag), minor (e.g., 1.25.x), major (e.g., 1.x), latest</li>
          <li>Auto-update will automatically pull and recreate containers when updates are available</li>
          <li>Container health is verified after updates to ensure successful deployment</li>
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
