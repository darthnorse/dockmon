/**
 * Container Health Check Tab
 *
 * Shows HTTP/HTTPS health check configuration and status
 */

import { memo, useState, useEffect } from 'react'
import { Activity, RefreshCw, CheckCircle2, XCircle, Clock, AlertTriangle, FlaskConical } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { toast } from 'sonner'
import { useContainerHealthCheck, useUpdateHealthCheck, useTestHealthCheck } from '../../hooks/useContainerHealthCheck'
import type { Container } from '../../types'

export interface ContainerHealthCheckTabProps {
  container: Container
}

function ContainerHealthCheckTabInternal({ container }: ContainerHealthCheckTabProps) {
  // CRITICAL: Always use 12-char short ID for API calls (backend expects short IDs)
  const containerShortId = container.id.slice(0, 12)

  const { data: healthCheck, isLoading, error } = useContainerHealthCheck(
    container.host_id,
    containerShortId
  )
  const updateHealthCheck = useUpdateHealthCheck()
  const testHealthCheck = useTestHealthCheck()

  // Local state for form
  const [enabled, setEnabled] = useState(false)
  const [url, setUrl] = useState('')
  const [method, setMethod] = useState('GET')
  const [expectedStatusCodes, setExpectedStatusCodes] = useState('200')
  const [timeoutSeconds, setTimeoutSeconds] = useState(10)
  const [checkIntervalSeconds, setCheckIntervalSeconds] = useState(60)
  const [followRedirects, setFollowRedirects] = useState(true)
  const [verifySsl, setVerifySsl] = useState(true)
  const [checkFrom, setCheckFrom] = useState<'backend' | 'agent'>('backend')  // v2.2.0+
  const [autoRestartOnFailure, setAutoRestartOnFailure] = useState(false)
  const [failureThreshold, setFailureThreshold] = useState(3)
  const [successThreshold, setSuccessThreshold] = useState(1)
  const [maxRestartAttempts, setMaxRestartAttempts] = useState(3)  // v2.0.2+
  const [restartRetryDelaySeconds, setRestartRetryDelaySeconds] = useState(120)  // v2.0.2+

  // Sync local state when server data changes
  useEffect(() => {
    if (healthCheck) {
      setEnabled(healthCheck.enabled)
      setUrl(healthCheck.url || '')
      setMethod(healthCheck.method || 'GET')
      setExpectedStatusCodes(healthCheck.expected_status_codes || '200')
      setTimeoutSeconds(healthCheck.timeout_seconds ?? 10)
      setCheckIntervalSeconds(healthCheck.check_interval_seconds ?? 60)
      setFollowRedirects(healthCheck.follow_redirects ?? true)
      setVerifySsl(healthCheck.verify_ssl ?? true)
      setCheckFrom(healthCheck.check_from ?? 'backend')  // v2.2.0+
      setAutoRestartOnFailure(healthCheck.auto_restart_on_failure ?? false)
      setFailureThreshold(healthCheck.failure_threshold ?? 3)
      setSuccessThreshold(healthCheck.success_threshold ?? 1)
      setMaxRestartAttempts(healthCheck.max_restart_attempts ?? 3)  // v2.0.2+
      setRestartRetryDelaySeconds(healthCheck.restart_retry_delay_seconds ?? 120)  // v2.0.2+
    }
  }, [healthCheck])

  // Log any errors for debugging
  if (error) {
    console.error('Error fetching health check:', error)
  }

  const handleTest = async () => {
    if (!container.host_id) {
      toast.error('Cannot test health check', {
        description: 'Container missing host information',
      })
      return
    }

    if (!url) {
      toast.error('URL is required', {
        description: 'Please enter a URL to test',
      })
      return
    }

    try {
      const result = await testHealthCheck.mutateAsync({
        hostId: container.host_id,
        containerId: containerShortId,
        config: {
          url,
          method,
          expected_status_codes: expectedStatusCodes,
          timeout_seconds: timeoutSeconds,
          follow_redirects: followRedirects,
          verify_ssl: verifySsl,
        },
      })

      if (result.is_healthy) {
        toast.success('Health check test passed!', {
          description: `${result.message} (${result.response_time_ms}ms)`,
        })
      } else {
        toast.error('Health check test failed', {
          description: result.message,
        })
      }
    } catch (error) {
      toast.error('Failed to test health check', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    }
  }

  const handleSave = async () => {
    if (!container.host_id) {
      toast.error('Cannot save health check', {
        description: 'Container missing host information',
      })
      return
    }

    if (enabled && !url) {
      toast.error('URL is required', {
        description: 'Please enter a URL to check',
      })
      return
    }

    try {
      await updateHealthCheck.mutateAsync({
        hostId: container.host_id,
        containerId: containerShortId,
        config: {
          // Only send configuration fields, not read-only state tracking fields
          enabled,
          url,
          method,
          expected_status_codes: expectedStatusCodes,
          timeout_seconds: timeoutSeconds,
          check_interval_seconds: checkIntervalSeconds,
          follow_redirects: followRedirects,
          verify_ssl: verifySsl,
          check_from: checkFrom,  // v2.2.0+
          auto_restart_on_failure: autoRestartOnFailure,
          failure_threshold: failureThreshold,
          success_threshold: successThreshold,
          max_restart_attempts: maxRestartAttempts,  // v2.0.2+
          restart_retry_delay_seconds: restartRetryDelaySeconds,  // v2.0.2+
        },
      })
      toast.success('Health check configuration saved')
    } catch (error) {
      toast.error('Failed to save configuration', {
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

  // Check if health check record exists in database
  // Backend returns null for consecutive_failures when no record exists
  const healthCheckExists = healthCheck && healthCheck.consecutive_failures !== null

  const currentStatus = healthCheck?.current_status || 'unknown'
  const lastChecked = healthCheck?.last_checked_at
    ? new Date(healthCheck.last_checked_at).toLocaleString()
    : 'Never'

  const getStatusIcon = () => {
    switch (currentStatus) {
      case 'healthy':
        return <CheckCircle2 className="h-8 w-8 text-success" />
      case 'unhealthy':
        return <XCircle className="h-8 w-8 text-danger" />
      default:
        return <Activity className="h-8 w-8 text-muted-foreground" />
    }
  }

  const getStatusText = () => {
    switch (currentStatus) {
      case 'healthy':
        return { title: 'Healthy', description: 'The container is responding as expected' }
      case 'unhealthy':
        return { title: 'Unhealthy', description: healthCheck?.last_error_message || 'Health check is failing' }
      default:
        return { title: 'Unknown', description: enabled ? 'Waiting for first health check' : 'Health check is not enabled' }
    }
  }

  const status = getStatusText()

  return (
    <div className="p-6 space-y-6">
      {/* Header with status */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {getStatusIcon()}
          <div>
            <h3 className={`text-lg font-semibold ${
              currentStatus === 'healthy' ? 'text-success' :
              currentStatus === 'unhealthy' ? 'text-danger' :
              'text-foreground'
            }`}>
              {status.title}
            </h3>
            <p className="text-sm text-muted-foreground">
              {status.description}
            </p>
          </div>
        </div>

        <div className="flex gap-2">
          <Button
            onClick={handleTest}
            disabled={testHealthCheck.isPending || !url || !healthCheckExists}
            variant="outline"
            title={!healthCheckExists ? 'Save configuration first to test' : ''}
          >
            {testHealthCheck.isPending ? (
              <>
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                Testing...
              </>
            ) : (
              <>
                <FlaskConical className="mr-2 h-4 w-4" />
                Check Now
              </>
            )}
          </Button>

          <Button
            onClick={handleSave}
            disabled={updateHealthCheck.isPending}
            variant="default"
          >
            {updateHealthCheck.isPending ? (
              <>
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                Saving...
              </>
            ) : (
              'Save Changes'
            )}
          </Button>
        </div>
      </div>

      {/* Current Status Details (if enabled and has data) */}
      {enabled && healthCheck?.last_checked_at && (
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-muted rounded-lg p-4">
            <div className="flex items-center gap-2 text-muted-foreground mb-1">
              <Clock className="h-4 w-4" />
              <span className="text-xs font-medium">Last Checked</span>
            </div>
            <p className="text-sm font-medium">{lastChecked}</p>
          </div>

          {healthCheck.last_response_time_ms !== null && (
            <div className="bg-muted rounded-lg p-4">
              <div className="flex items-center gap-2 text-muted-foreground mb-1">
                <Activity className="h-4 w-4" />
                <span className="text-xs font-medium">Response Time</span>
              </div>
              <p className="text-sm font-medium">{healthCheck.last_response_time_ms}ms</p>
            </div>
          )}

          {healthCheck.consecutive_failures !== null && healthCheck.consecutive_failures > 0 && (
            <div className="bg-danger/10 rounded-lg p-4">
              <div className="flex items-center gap-2 text-danger mb-1">
                <AlertTriangle className="h-4 w-4" />
                <span className="text-xs font-medium">Consecutive Failures</span>
              </div>
              <p className="text-sm font-medium text-danger">
                {healthCheck.consecutive_failures} / {healthCheck.failure_threshold}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Configuration Form */}
      <div className="space-y-4 border-t pt-6">
        <h4 className="text-lg font-medium text-foreground mb-3">Configuration</h4>

        {/* Enable/Disable toggle */}
        <div className="flex items-start justify-between py-4">
          <div className="flex-1 mr-4">
            <label htmlFor="health-check-enabled" className="text-sm font-medium cursor-pointer">
              Enable Health Check
            </label>
            <p className="text-sm text-muted-foreground mt-1">
              Monitor this container with HTTP/HTTPS health checks
            </p>
          </div>
          <Switch
            id="health-check-enabled"
            checked={enabled}
            onCheckedChange={setEnabled}
          />
        </div>

        {/* URL */}
        <div className="space-y-2">
          <label htmlFor="url" className="text-sm font-medium">
            URL <span className="text-danger">*</span>
          </label>
          <Input
            id="url"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="http://localhost:8080/health"
            disabled={!enabled}
          />
          <p className="text-xs text-muted-foreground">
            Full URL to check (e.g., http://localhost:8080/health)
          </p>
        </div>

        {/* Method and Expected Status Codes */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label htmlFor="method" className="text-sm font-medium">
              HTTP Method
            </label>
            <Select
              value={method}
              onValueChange={setMethod}
              disabled={!enabled}
            >
              <SelectTrigger id="method">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="GET">GET</SelectItem>
                <SelectItem value="POST">POST</SelectItem>
                <SelectItem value="HEAD">HEAD</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <label htmlFor="status-codes" className="text-sm font-medium">
              Expected Status Codes
            </label>
            <Input
              id="status-codes"
              value={expectedStatusCodes}
              onChange={(e) => setExpectedStatusCodes(e.target.value)}
              placeholder="200"
              disabled={!enabled}
            />
            <p className="text-xs text-muted-foreground">
              e.g., "200" or "200-299" or "200,201,204"
            </p>
          </div>
        </div>

        {/* Timeout and Interval */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label htmlFor="timeout" className="text-sm font-medium">
              Timeout (seconds)
            </label>
            <Input
              id="timeout"
              type="number"
              min="5"
              max="60"
              value={timeoutSeconds}
              onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
              disabled={!enabled}
            />
          </div>

          <div className="space-y-2">
            <label htmlFor="interval" className="text-sm font-medium">
              Check Interval (seconds)
            </label>
            <Input
              id="interval"
              type="number"
              min="10"
              max="3600"
              value={checkIntervalSeconds}
              onChange={(e) => setCheckIntervalSeconds(Number(e.target.value))}
              disabled={!enabled}
            />
          </div>
        </div>

        {/* Failure and Success Thresholds */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label htmlFor="failure-threshold" className="text-sm font-medium">
              Failure Threshold
            </label>
            <Input
              id="failure-threshold"
              type="number"
              min="1"
              max="10"
              value={failureThreshold}
              onChange={(e) => setFailureThreshold(Number(e.target.value))}
              disabled={!enabled}
            />
            <p className="text-xs text-muted-foreground">
              Consecutive failures before marking as unhealthy
            </p>
          </div>

          <div className="space-y-2">
            <label htmlFor="success-threshold" className="text-sm font-medium">
              Success Threshold
            </label>
            <Input
              id="success-threshold"
              type="number"
              min="1"
              max="10"
              value={successThreshold}
              onChange={(e) => setSuccessThreshold(Number(e.target.value))}
              disabled={!enabled}
            />
            <p className="text-xs text-muted-foreground">
              Consecutive successes to mark as healthy after failure
            </p>
          </div>
        </div>

        {/* SSL and Redirects */}
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-start justify-between py-2">
            <div className="flex-1 mr-4">
              <label htmlFor="verify-ssl" className="text-sm font-medium cursor-pointer">
                Verify SSL
              </label>
              <p className="text-xs text-muted-foreground mt-1">
                Validate SSL certificates
              </p>
            </div>
            <Switch
              id="verify-ssl"
              checked={verifySsl}
              onCheckedChange={setVerifySsl}
              disabled={!enabled}
            />
          </div>

          <div className="flex items-start justify-between py-2">
            <div className="flex-1 mr-4">
              <label htmlFor="follow-redirects" className="text-sm font-medium cursor-pointer">
                Follow Redirects
              </label>
              <p className="text-xs text-muted-foreground mt-1">
                Follow HTTP redirects
              </p>
            </div>
            <Switch
              id="follow-redirects"
              checked={followRedirects}
              onCheckedChange={setFollowRedirects}
              disabled={!enabled}
            />
          </div>
        </div>

        {/* Check Location (v2.2.0+) */}
        <div className="space-y-2">
          <label htmlFor="check-from" className="text-sm font-medium">
            Check From
          </label>
          <Select
            value={checkFrom}
            onValueChange={(value) => setCheckFrom(value as 'backend' | 'agent')}
            disabled={!enabled}
          >
            <SelectTrigger id="check-from">
              <SelectValue>
                {checkFrom === 'backend' ? 'DockMon Backend' : 'Remote Agent'}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="backend">DockMon Backend</SelectItem>
              <SelectItem value="agent">Remote Agent</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            {checkFrom === 'backend'
              ? 'Health checks performed from the DockMon backend server'
              : 'Health checks performed from the agent on the remote host (useful when backend cannot reach the container)'}
          </p>
        </div>

        {/* Auto-restart section */}
        <div className="border-t pt-4 space-y-4">
          <div className="flex items-start justify-between py-2">
            <div className="flex-1 mr-4">
              <label htmlFor="auto-restart" className="text-sm font-medium cursor-pointer">
                Auto-restart on Failure
              </label>
              <p className="text-sm text-muted-foreground mt-1">
                Automatically restart container when failure threshold is reached
              </p>
            </div>
            <Switch
              id="auto-restart"
              checked={autoRestartOnFailure}
              onCheckedChange={setAutoRestartOnFailure}
              disabled={!enabled}
            />
          </div>

          {/* Retry configuration (v2.0.2+) - only show when auto-restart is enabled */}
          {autoRestartOnFailure && (
            <div className="grid grid-cols-2 gap-4 pl-4 border-l-2 border-muted">
              <div className="space-y-2">
                <label htmlFor="max-restart-attempts" className="text-sm font-medium">
                  Max Restart Attempts
                </label>
                <Input
                  id="max-restart-attempts"
                  type="number"
                  min="1"
                  max="10"
                  value={maxRestartAttempts}
                  onChange={(e) => setMaxRestartAttempts(Number(e.target.value))}
                  disabled={!enabled}
                />
                <p className="text-xs text-muted-foreground">
                  Number of restart attempts per unhealthy episode (resets on recovery)
                </p>
              </div>

              <div className="space-y-2">
                <label htmlFor="restart-retry-delay" className="text-sm font-medium">
                  Retry Delay (seconds)
                </label>
                <Input
                  id="restart-retry-delay"
                  type="number"
                  min="30"
                  max="600"
                  value={restartRetryDelaySeconds}
                  onChange={(e) => setRestartRetryDelaySeconds(Number(e.target.value))}
                  disabled={!enabled}
                />
                <p className="text-xs text-muted-foreground">
                  Delay between restart attempts. Note: 10-minute safety window allows max 12 total restarts (long delays may limit attempts)
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Help text */}
      <div className="bg-muted/50 rounded-lg p-4 text-sm text-muted-foreground space-y-2">
        <p className="font-medium">About HTTP Health Checks</p>
        <ul className="list-disc list-inside space-y-1 text-xs">
          <li>Health checks periodically request a URL to verify container is responding</li>
          <li>Consecutive failures must reach the threshold before marking as unhealthy</li>
          <li>Auto-restart can automatically restart containers that fail health checks</li>
          <li>Health state changes trigger alerts if configured in alert rules</li>
          <li>Use internal URLs (localhost/container network) for best performance</li>
        </ul>
      </div>
    </div>
  )
}

// Memoize component to prevent unnecessary re-renders
export const ContainerHealthCheckTab = memo(ContainerHealthCheckTabInternal, (prevProps, nextProps) => {
  const areEqual = (
    prevProps.container.id === nextProps.container.id &&
    prevProps.container.host_id === nextProps.container.host_id
  )
  return areEqual
})
