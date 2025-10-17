/**
 * Host Modal Component - Phase 3d Sub-Phase 6
 *
 * FEATURES:
 * - Add/Edit host modal with TLS support
 * - React Hook Form + Zod validation
 * - TagInput integration for host tags
 * - TLS certificate fields (expandable)
 * - Description textarea
 *
 * FIELDS:
 * - Host Name (required)
 * - Address/Endpoint (required)
 * - TLS Toggle (expands certificate fields)
 * - CA Certificate (textarea, TLS only)
 * - Client Certificate (textarea, mTLS)
 * - Client Key (textarea, mTLS)
 * - Tags (TagInput multi-select)
 * - Description (textarea)
 */

import { useState, useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'

// Type for API errors
interface ApiError extends Error {
  response?: {
    data?: {
      detail?: string
    }
  }
}
import { X, Trash2, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { TagInput } from '@/components/TagInput'
import { useTags } from '@/lib/hooks/useTags'
import { useAddHost, useUpdateHost, useDeleteHost, type HostConfig } from '../hooks/useHosts'
import type { Host } from '@/types/api'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import { useAllContainers } from '@/lib/stats/StatsProvider'
import { useQuery } from '@tanstack/react-query'

// Zod schema for host form
const hostSchema = z.object({
  name: z
    .string()
    .min(1, 'Host name is required')
    .max(100, 'Host name must be less than 100 characters')
    .regex(/^[a-zA-Z0-9][a-zA-Z0-9 ._-]*$/, 'Host name contains invalid characters'),
  url: z
    .string()
    .min(1, 'Address/Endpoint is required')
    .regex(
      /^(tcp|unix|http|https):\/\/.+/,
      'URL must start with tcp://, unix://, http://, or https://'
    ),
  enableTls: z.boolean(),
  tls_ca: z.string().optional(),
  tls_cert: z.string().optional(),
  tls_key: z.string().optional(),
  tags: z.array(z.string()).max(50, 'Maximum 50 tags allowed').optional(),
  description: z.string().max(1000, 'Description must be less than 1000 characters').optional(),
})

type HostFormData = z.infer<typeof hostSchema>

interface HostModalProps {
  isOpen: boolean
  onClose: () => void
  host?: Host | null // If editing
}

export function HostModal({ isOpen, onClose, host }: HostModalProps) {
  const [showTlsFields, setShowTlsFields] = useState(false)
  const [replaceCa, setReplaceCa] = useState(false)
  const [replaceCert, setReplaceCert] = useState(false)
  const [replaceKey, setReplaceKey] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const { tags: allTags } = useTags()
  const addMutation = useAddHost()
  const updateMutation = useUpdateHost()
  const deleteMutation = useDeleteHost()

  // Get containers for this host (for delete confirmation)
  const containers = useAllContainers(host?.id || undefined)

  // Get open alerts for this host (for delete confirmation)
  const { data: alertsData } = useQuery({
    queryKey: ['alerts', 'host', host?.id],
    queryFn: async () => {
      const response = await apiClient.get<{ alerts: any[]; total: number }>(
        `/alerts/?state=open&scope_type=host&page_size=500`
      )
      return response.alerts.filter((alert: any) => alert.host_id === host?.id)
    },
    enabled: showDeleteConfirm && !!host?.id, // Only fetch when delete dialog is open and host exists
  })

  const openAlerts = alertsData || []

  // Check if host has existing certificates (indicates mTLS is enabled)
  const hostHasCerts = host?.security_status === 'secure'

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<HostFormData>({
    resolver: zodResolver(hostSchema),
    defaultValues: {
      name: host?.name || '',
      url: host?.url || '',
      enableTls: hostHasCerts || false,
      tls_ca: '',
      tls_cert: '',
      tls_key: '',
      tags: host?.tags || [],
      description: host?.description || '',
    },
  })

  const watchTags = watch('tags')
  const watchUrl = watch('url')

  // Update form when host prop changes or modal opens
  useEffect(() => {
    if (host) {
      // Edit mode - populate with host data
      const hasCerts = host.security_status === 'secure'
      setShowTlsFields(hasCerts)
      setReplaceCa(false)
      setReplaceCert(false)
      setReplaceKey(false)

      reset({
        name: host.name,
        url: host.url,
        enableTls: hasCerts,
        tls_ca: '',
        tls_cert: '',
        tls_key: '',
        tags: host.tags || [],
        description: host.description || '',
      })
    } else {
      // Add mode - reset to empty form
      setShowTlsFields(false)
      setReplaceCa(false)
      setReplaceCert(false)
      setReplaceKey(false)

      reset({
        name: '',
        url: '',
        enableTls: false,
        tls_ca: '',
        tls_cert: '',
        tls_key: '',
        tags: [],
        description: '',
      })
    }
  }, [host, isOpen, reset])

  const testConnection = async () => {
    const formData = watch()

    // Validate required fields
    if (!formData.url) {
      toast.error('Please enter an address/endpoint first')
      return
    }

    // Build test config
    const testConfig: HostConfig = {
      name: formData.name || 'test',
      url: formData.url,
      tags: [],
      description: null,
    }

    // Add certs if mTLS is enabled
    if (showTlsFields) {
      // For existing hosts with certs, we can't test without replacement
      if (hostHasCerts && !replaceCa && !replaceCert && !replaceKey) {
        toast.info('Using existing certificates for test connection')
        // Send empty certs - backend will use existing ones
        testConfig.tls_ca = null
        testConfig.tls_cert = null
        testConfig.tls_key = null
      } else {
        // New certs or replacement - validate they're provided
        if (!formData.tls_ca || !formData.tls_cert || !formData.tls_key) {
          toast.error('All three certificates are required for mTLS connection')
          return
        }
        testConfig.tls_ca = formData.tls_ca
        testConfig.tls_cert = formData.tls_cert
        testConfig.tls_key = formData.tls_key
      }
    }

    try {
      toast.loading('Testing connection...', { id: 'test-connection' })

      const response = await apiClient.post<{
        success: boolean
        message: string
        docker_version: string
        api_version: string
      }>('/hosts/test-connection', testConfig)

      const dockerVersion = response.docker_version || 'unknown'
      const apiVersion = response.api_version || 'unknown'

      toast.success(`Connection successful! Docker ${dockerVersion} (API ${apiVersion})`, {
        id: 'test-connection',
        duration: 5000
      })
    } catch (error: unknown) {
      const apiError = error as ApiError
      const message = apiError.response?.data?.detail || apiError.message || 'Connection failed'
      toast.error(message, { id: 'test-connection' })
    }
  }

  const onSubmit = async (data: HostFormData) => {
    const config: HostConfig = {
      name: data.name,
      url: data.url,
      tags: data.tags || [],
      description: data.description || null,
    }

    // Add TLS fields if enabled
    if (data.enableTls) {
      // For existing hosts, only send certs if user clicked Replace
      if (host && hostHasCerts) {
        config.tls_ca = replaceCa ? (data.tls_ca || null) : null
        config.tls_cert = replaceCert ? (data.tls_cert || null) : null
        config.tls_key = replaceKey ? (data.tls_key || null) : null
      } else {
        // New host or new mTLS setup - send all certs
        config.tls_ca = data.tls_ca || null
        config.tls_cert = data.tls_cert || null
        config.tls_key = data.tls_key || null
      }
    }

    try {
      if (host) {
        // Update existing host
        await updateMutation.mutateAsync({ id: host.id, config })
      } else {
        // Add new host
        await addMutation.mutateAsync(config)
      }
      onClose()
      reset()
    } catch (error) {
      // Error handled by mutation hooks (toast)
      debug.error('HostModal', 'Error saving host:', error)
    }
  }

  const handleDeleteClick = () => {
    setShowDeleteConfirm(true)
  }

  const handleDeleteConfirm = async () => {
    if (!host) return

    try {
      await deleteMutation.mutateAsync(host.id)
      setShowDeleteConfirm(false)
      onClose()
    } catch (error) {
      // Error is handled by the mutation's onError
      setShowDeleteConfirm(false)
    }
  }

  const handleDeleteCancel = () => {
    setShowDeleteConfirm(false)
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" data-testid="host-modal">
      <div
        className="relative w-full max-w-lg rounded-2xl border border-border bg-background p-6 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-semibold">
              {host ? 'Edit Host' : 'Add Host'}
            </h2>
            <p className="text-sm text-muted-foreground mt-1">
              Provide connection details for a Docker host
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
            data-testid="host-modal-close"
          >
            <X className="h-4 w-4" />
            <span className="sr-only">Close</span>
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* Host Name */}
          <div>
            <label htmlFor="name" className="block text-sm font-medium mb-1">
              Host Name <span className="text-destructive">*</span>
            </label>
            <Input
              id="name"
              {...register('name')}
              placeholder="docker-prod-01"
              className={errors.name ? 'border-destructive' : ''}
              data-testid="host-name-input"
            />
            {errors.name && (
              <p className="text-xs text-destructive mt-1">{errors.name.message}</p>
            )}
          </div>

          {/* Address/Endpoint */}
          <div>
            <label htmlFor="url" className="block text-sm font-medium mb-1">
              Address / Endpoint <span className="text-destructive">*</span>
            </label>
            <Input
              id="url"
              {...register('url')}
              placeholder="tcp://192.168.1.20:2376 or unix:///var/run/docker.sock"
              className={errors.url ? 'border-destructive' : ''}
              data-testid="host-url-input"
            />
            {errors.url && (
              <p className="text-xs text-destructive mt-1">{errors.url.message}</p>
            )}
          </div>

          {/* TLS Toggle or UNIX Socket Note */}
          {watchUrl?.startsWith('unix://') ? (
            <div className="rounded-lg border border-border p-3 bg-muted/10">
              <p className="text-sm text-muted-foreground">
                Local UNIX socket — TLS not applicable
              </p>
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="enableTls"
                    checked={showTlsFields}
                    onChange={(e) => {
                      const checked = e.target.checked
                      setShowTlsFields(checked)
                      setValue('enableTls', checked)
                    }}
                    className="h-4 w-4"
                    data-testid="host-enable-tls"
                  />
                  <label htmlFor="enableTls" className="text-sm font-medium">
                    Enable mTLS (mutual TLS)
                  </label>
                </div>
                {!showTlsFields && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={testConnection}
                    className="h-7 text-xs"
                  >
                    Test Connection
                  </Button>
                )}
              </div>

              {/* mTLS Certificate Fields (conditional) */}
              {showTlsFields && (
                <div className="space-y-4 rounded-lg border border-border p-4 bg-muted/20">
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-muted-foreground">
                      All three certificates are required for secure mTLS connection.
                    </p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={testConnection}
                      className="h-7 text-xs"
                    >
                      Test Connection
                    </Button>
                  </div>

                  {/* CA Certificate */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label htmlFor="tls_ca" className="block text-sm font-medium">
                        CA Certificate <span className="text-destructive">*</span>
                      </label>
                      {hostHasCerts && !replaceCa && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setReplaceCa(true)}
                          className="h-7 text-xs"
                        >
                          Replace
                        </Button>
                      )}
                    </div>
                    {hostHasCerts && !replaceCa ? (
                      <div className="w-full rounded-md border border-input bg-muted px-3 py-2 text-sm text-muted-foreground">
                        Uploaded — •••
                      </div>
                    ) : (
                      <textarea
                        id="tls_ca"
                        {...register('tls_ca')}
                        rows={4}
                        placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                        data-testid="host-tls-ca"
                      />
                    )}
                    {errors.tls_ca && (
                      <p className="text-xs text-destructive mt-1">{errors.tls_ca.message}</p>
                    )}
                  </div>

                  {/* Client Certificate */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label htmlFor="tls_cert" className="block text-sm font-medium">
                        Client Certificate <span className="text-destructive">*</span>
                      </label>
                      {hostHasCerts && !replaceCert && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setReplaceCert(true)}
                          className="h-7 text-xs"
                        >
                          Replace
                        </Button>
                      )}
                    </div>
                    {hostHasCerts && !replaceCert ? (
                      <div className="w-full rounded-md border border-input bg-muted px-3 py-2 text-sm text-muted-foreground">
                        Uploaded — •••
                      </div>
                    ) : (
                      <textarea
                        id="tls_cert"
                        {...register('tls_cert')}
                        rows={4}
                        placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                        data-testid="host-tls-cert"
                      />
                    )}
                    {errors.tls_cert && (
                      <p className="text-xs text-destructive mt-1">{errors.tls_cert.message}</p>
                    )}
                  </div>

                  {/* Client Key */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label htmlFor="tls_key" className="block text-sm font-medium">
                        Client Private Key <span className="text-destructive">*</span>
                      </label>
                      {hostHasCerts && !replaceKey && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          onClick={() => setReplaceKey(true)}
                          className="h-7 text-xs"
                        >
                          Replace
                        </Button>
                      )}
                    </div>
                    {hostHasCerts && !replaceKey ? (
                      <div className="w-full rounded-md border border-input bg-muted px-3 py-2 text-sm text-muted-foreground">
                        Uploaded — •••
                      </div>
                    ) : (
                      <textarea
                        id="tls_key"
                        {...register('tls_key')}
                        rows={4}
                        placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
                        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                        data-testid="host-tls-key"
                      />
                    )}
                    {errors.tls_key && (
                      <p className="text-xs text-destructive mt-1">{errors.tls_key.message}</p>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Tags */}
          <div>
            <label htmlFor="tags" className="block text-sm font-medium mb-1">
              Tags / Groups
            </label>
            <TagInput
              value={watchTags || []}
              onChange={(tags) => setValue('tags', tags)}
              suggestions={allTags}
              placeholder="Add tags for organization..."
              showPrimaryIndicator={true}
            />
            {errors.tags && (
              <p className="text-xs text-destructive mt-1">{errors.tags.message}</p>
            )}
          </div>

          {/* Description */}
          <div>
            <label htmlFor="description" className="block text-sm font-medium mb-1">
              Description
            </label>
            <textarea
              id="description"
              {...register('description')}
              rows={3}
              placeholder="Optional notes about this host..."
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              data-testid="host-description"
            />
            {errors.description && (
              <p className="text-xs text-destructive mt-1">{errors.description.message}</p>
            )}
          </div>

          {/* Footer Actions */}
          <div className="flex justify-between gap-2 pt-4 border-t">
            {/* Delete Button - Only show when editing */}
            {host ? (
              <Button
                type="button"
                variant="outline"
                onClick={handleDeleteClick}
                disabled={deleteMutation.isPending}
                className="text-red-500 hover:text-red-600 hover:bg-red-50"
                data-testid="host-modal-delete"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
              </Button>
            ) : (
              <div></div>
            )}

            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={onClose} data-testid="host-modal-cancel">
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting} data-testid="host-modal-save">
                {isSubmitting
                  ? 'Saving...'
                  : host
                  ? 'Update Host'
                  : 'Add Host'}
              </Button>
            </div>
          </div>
        </form>
      </div>

      {/* Delete Confirmation Dialog */}
      {showDeleteConfirm && host && (
        <div className="fixed inset-0 bg-black/70 z-[60] flex items-center justify-center p-4">
          <div className="bg-surface border border-border rounded-lg shadow-2xl max-w-md w-full p-6">
            <div className="flex items-start gap-4 mb-4">
              <div className="flex-shrink-0 w-12 h-12 rounded-full bg-red-500/10 flex items-center justify-center">
                <AlertTriangle className="h-6 w-6 text-red-500" />
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold mb-2">Delete Host</h3>
                <p className="text-sm text-muted-foreground mb-3">
                  Are you sure you want to delete <span className="font-semibold text-foreground">{host.name}</span>? This action cannot be undone.
                </p>

                {/* Show what will be affected */}
                <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-2 text-sm">
                  <p className="font-medium text-foreground mb-2">This will affect:</p>
                  <div className="space-y-1.5 text-muted-foreground">
                    <div className="flex items-center justify-between">
                      <span>Containers monitored:</span>
                      <span className="font-semibold text-foreground">{containers.length}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Open alerts:</span>
                      <span className="font-semibold text-foreground">{openAlerts.length} will be resolved</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Container settings:</span>
                      <span className="font-semibold text-foreground">Will be deleted</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Event history:</span>
                      <span className="font-semibold text-green-500">Preserved</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={handleDeleteCancel}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 rounded-lg border border-border bg-background hover:bg-muted transition-colors text-sm disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteConfirm}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 rounded-lg bg-red-500 hover:bg-red-600 text-white transition-colors text-sm disabled:opacity-50"
              >
                {deleteMutation.isPending ? 'Deleting...' : 'Delete Host'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
