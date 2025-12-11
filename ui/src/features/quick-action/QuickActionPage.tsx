/**
 * Quick Action Page
 *
 * Standalone page for executing one-time action tokens from notification links.
 * Requires authentication - redirects to login if not authenticated.
 *
 * Flow:
 * 1. User clicks link in notification (Pushover, Telegram, etc.)
 * 2. If not logged in -> redirect to login with return URL
 * 3. After login -> validates token and shows action details
 * 4. User confirms -> executes action
 * 5. Shows success/failure result
 */

import { useState, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { Container, ArrowRight, CheckCircle2, XCircle, Loader2, Clock, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface TokenInfo {
  valid: boolean
  reason?: string
  action_type?: string
  action_params?: {
    host_id?: string
    host_name?: string
    container_id?: string
    container_name?: string
    current_image?: string
    new_image?: string
  }
  created_at?: string
  expires_at?: string
  hours_remaining?: number
}

interface ExecuteResult {
  success: boolean
  action_type?: string
  result?: {
    message?: string
    previous_image?: string
    new_image?: string
  }
  error?: string
}

type PageState = 'loading' | 'invalid' | 'ready' | 'executing' | 'success' | 'error'

export function QuickActionPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const token = searchParams.get('token')

  const [state, setState] = useState<PageState>('loading')
  const [tokenInfo, setTokenInfo] = useState<TokenInfo | null>(null)
  const [executeResult, setExecuteResult] = useState<ExecuteResult | null>(null)
  const [errorMessage, setErrorMessage] = useState<string>('')

  // Validate token on mount
  useEffect(() => {
    if (!token) {
      setState('invalid')
      setErrorMessage('No token provided')
      return
    }

    validateToken()
  }, [token])

  const validateToken = async () => {
    try {
      const response = await fetch(`/api/v2/action-tokens/${encodeURIComponent(token!)}/info`, {
        credentials: 'include'  // Include session cookie
      })

      // If not authenticated, redirect to login with return URL
      if (response.status === 401) {
        const returnUrl = encodeURIComponent(window.location.pathname + window.location.search)
        navigate(`/login?redirect=${returnUrl}`)
        return
      }

      const data: TokenInfo = await response.json()

      setTokenInfo(data)

      if (data.valid) {
        setState('ready')
      } else {
        setState('invalid')
        setErrorMessage(getErrorMessage(data.reason))
      }
    } catch (error) {
      setState('invalid')
      setErrorMessage('Failed to validate token')
    }
  }

  const executeAction = async () => {
    if (!token || !tokenInfo?.action_params) return

    setState('executing')

    try {
      // Step 1: Consume the token (validates and marks as used)
      const consumeResponse = await fetch(`/api/v2/action-tokens/${encodeURIComponent(token!)}/consume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ confirmed: true }),
      })

      if (consumeResponse.status === 401) {
        const returnUrl = encodeURIComponent(window.location.pathname + window.location.search)
        navigate(`/login?redirect=${returnUrl}`)
        return
      }

      const consumeData = await consumeResponse.json()
      if (!consumeData.success) {
        setState('error')
        setErrorMessage(consumeData.error || 'Token validation failed')
        return
      }

      // Step 2: Call the EXISTING update endpoint (same code path as manual updates)
      const { host_id, container_id } = tokenInfo.action_params
      if (!host_id || !container_id) {
        setState('error')
        setErrorMessage('Missing host or container information')
        return
      }

      const updateResponse = await fetch(
        `/api/hosts/${encodeURIComponent(host_id)}/containers/${encodeURIComponent(container_id)}/execute-update?force=true`,
        {
          method: 'POST',
          credentials: 'include',
        }
      )

      if (updateResponse.status === 401) {
        const returnUrl = encodeURIComponent(window.location.pathname + window.location.search)
        navigate(`/login?redirect=${returnUrl}`)
        return
      }

      const updateData = await updateResponse.json()

      if (updateData.status === 'success') {
        setExecuteResult({
          success: true,
          action_type: 'container_update',
          result: {
            message: updateData.message,
            previous_image: updateData.previous_image,
            new_image: updateData.new_image,
          }
        })
        setState('success')
      } else {
        setState('error')
        setErrorMessage(updateData.detail || updateData.message || 'Update failed')
      }
    } catch (error) {
      setState('error')
      setErrorMessage('Failed to execute action')
    }
  }

  const getErrorMessage = (reason?: string): string => {
    switch (reason) {
      case 'expired':
        return 'This link has expired'
      case 'already_used':
        return 'This link has already been used'
      case 'revoked':
        return 'This link has been revoked'
      case 'not_found':
        return 'Invalid or unknown link'
      default:
        return 'Invalid link'
    }
  }

  const formatTimeRemaining = (hours?: number): string => {
    if (!hours) return ''
    if (hours < 1) {
      const minutes = Math.round(hours * 60)
      return `${minutes}m remaining`
    }
    return `${Math.round(hours)}h remaining`
  }

  return (
    <div className="min-h-screen bg-[#0a0e14] flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2 mb-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
              <Container className="h-6 w-6 text-primary" />
            </div>
            <span className="text-2xl font-semibold text-white">DockMon</span>
          </div>
          <p className="text-sm text-gray-400">Quick Action</p>
        </div>

        {/* Content Card */}
        <div className="bg-[#0d1117] border border-gray-800 rounded-xl p-6">
          {/* Loading State */}
          {state === 'loading' && (
            <div className="text-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto mb-4" />
              <p className="text-gray-400">Validating link...</p>
            </div>
          )}

          {/* Invalid Token State */}
          {state === 'invalid' && (
            <div className="text-center py-8">
              <XCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
              <h2 className="text-xl font-semibold text-white mb-2">Link Invalid</h2>
              <p className="text-gray-400">{errorMessage}</p>
            </div>
          )}

          {/* Ready State - Show Action Details */}
          {state === 'ready' && tokenInfo?.action_params && (
            <>
              <h2 className="text-lg font-semibold text-white mb-4">
                {tokenInfo.action_type === 'container_update' ? 'Update Container' : 'Confirm Action'}
              </h2>

              {/* Container Info */}
              <div className="bg-[#161b22] rounded-lg p-4 mb-4">
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Container</span>
                    <span className="text-white font-medium">{tokenInfo.action_params.container_name}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-gray-400">Host</span>
                    <span className="text-white">{tokenInfo.action_params.host_name || 'Unknown'}</span>
                  </div>
                </div>

                {/* Image Change */}
                {tokenInfo.action_params.current_image && tokenInfo.action_params.new_image && (
                  <div className="mt-4 pt-4 border-t border-gray-700">
                    <div className="flex items-center justify-center gap-2 text-sm">
                      <span className="text-gray-400 font-mono text-xs truncate max-w-[140px]" title={tokenInfo.action_params.current_image}>
                        {tokenInfo.action_params.current_image.split(':').pop()}
                      </span>
                      <ArrowRight className="h-4 w-4 text-primary flex-shrink-0" />
                      <span className="text-green-400 font-mono text-xs truncate max-w-[140px]" title={tokenInfo.action_params.new_image}>
                        {tokenInfo.action_params.new_image.split(':').pop()}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              {/* What will happen */}
              <div className="text-xs text-gray-400 mb-4">
                <p className="mb-2">This will:</p>
                <ul className="list-disc list-inside space-y-1 text-gray-500">
                  <li>Pull the new image</li>
                  <li>Stop the current container</li>
                  <li>Start with new image</li>
                  <li>Rollback if health check fails</li>
                </ul>
              </div>

              {/* Time Remaining */}
              {tokenInfo.hours_remaining && (
                <div className="flex items-center gap-2 text-xs text-gray-500 mb-4">
                  <Clock className="h-3 w-3" />
                  <span>Link {formatTimeRemaining(tokenInfo.hours_remaining)}</span>
                </div>
              )}

              {/* Action Buttons */}
              <div className="space-y-2">
                <Button
                  onClick={executeAction}
                  className="w-full"
                  size="lg"
                >
                  Confirm Update
                </Button>
                <Button
                  variant="outline"
                  className="w-full"
                  onClick={() => window.close()}
                >
                  Cancel
                </Button>
              </div>
            </>
          )}

          {/* Executing State */}
          {state === 'executing' && (
            <div className="text-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-primary mx-auto mb-4" />
              <p className="text-white font-medium mb-2">Updating container...</p>
              <p className="text-gray-400 text-sm">This may take a minute</p>
            </div>
          )}

          {/* Success State */}
          {state === 'success' && executeResult?.result && (
            <div className="text-center py-8">
              <CheckCircle2 className="h-12 w-12 text-green-500 mx-auto mb-4" />
              <h2 className="text-xl font-semibold text-white mb-2">Update Complete</h2>
              <p className="text-gray-400 text-sm mb-4">
                {executeResult.result.message || 'Container updated successfully'}
              </p>

              {executeResult.result.previous_image && executeResult.result.new_image && (
                <div className="bg-[#161b22] rounded-lg p-3 text-xs">
                  <div className="flex items-center justify-center gap-2">
                    <span className="text-gray-400 font-mono">{executeResult.result.previous_image.split(':').pop()}</span>
                    <ArrowRight className="h-3 w-3 text-primary" />
                    <span className="text-green-400 font-mono">{executeResult.result.new_image.split(':').pop()}</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Error State */}
          {state === 'error' && (
            <div className="text-center py-8">
              <AlertTriangle className="h-12 w-12 text-red-500 mx-auto mb-4" />
              <h2 className="text-xl font-semibold text-white mb-2">Update Failed</h2>
              <p className="text-gray-400 text-sm">{errorMessage}</p>
              {executeResult?.error?.includes('rolled back') && (
                <p className="text-yellow-500 text-xs mt-2">Container was rolled back to previous version</p>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-gray-600 mt-4">
          Powered by DockMon
        </p>
      </div>
    </div>
  )
}
