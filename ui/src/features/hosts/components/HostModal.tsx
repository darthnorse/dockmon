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
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { TagInput } from '@/components/TagInput'
import { useTags } from '@/lib/hooks/useTags'
import { useAddHost, useUpdateHost, type Host, type HostConfig } from '../hooks/useHosts'

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
  const { tags: allTags } = useTags()
  const addMutation = useAddHost()
  const updateMutation = useUpdateHost()

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
      enableTls: false,
      tls_ca: '',
      tls_cert: '',
      tls_key: '',
      tags: host?.tags || [],
      description: host?.description || '',
    },
  })

  const watchTags = watch('tags')

  // Update form when host prop changes
  useEffect(() => {
    if (host) {
      reset({
        name: host.name,
        url: host.url,
        enableTls: false,
        tls_ca: '',
        tls_cert: '',
        tls_key: '',
        tags: host.tags || [],
        description: host.description || '',
      })
    }
  }, [host, reset])

  const onSubmit = async (data: HostFormData) => {
    const config: HostConfig = {
      name: data.name,
      url: data.url,
      tags: data.tags || [],
      description: data.description || null,
    }

    // Add TLS fields if enabled
    if (data.enableTls) {
      config.tls_ca = data.tls_ca || null
      config.tls_cert = data.tls_cert || null
      config.tls_key = data.tls_key || null
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
      console.error('Error saving host:', error)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
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
            />
            {errors.url && (
              <p className="text-xs text-destructive mt-1">{errors.url.message}</p>
            )}
          </div>

          {/* TLS Toggle */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="enableTls"
              checked={showTlsFields}
              onChange={(e) => setShowTlsFields(e.target.checked)}
              className="h-4 w-4"
            />
            <label htmlFor="enableTls" className="text-sm font-medium">
              Enable TLS / mTLS
            </label>
          </div>

          {/* TLS Certificate Fields (conditional) */}
          {showTlsFields && (
            <div className="space-y-4 rounded-lg border border-border p-4 bg-muted/20">
              <p className="text-xs text-muted-foreground">
                Provide TLS certificates for secure connection. All three certificates are required for TLS.
              </p>

              {/* CA Certificate */}
              <div>
                <label htmlFor="tls_ca" className="block text-sm font-medium mb-1">
                  CA Certificate
                </label>
                <textarea
                  id="tls_ca"
                  {...register('tls_ca')}
                  rows={4}
                  placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                />
                {errors.tls_ca && (
                  <p className="text-xs text-destructive mt-1">{errors.tls_ca.message}</p>
                )}
              </div>

              {/* Client Certificate */}
              <div>
                <label htmlFor="tls_cert" className="block text-sm font-medium mb-1">
                  Client Certificate
                </label>
                <textarea
                  id="tls_cert"
                  {...register('tls_cert')}
                  rows={4}
                  placeholder="-----BEGIN CERTIFICATE-----&#10;...&#10;-----END CERTIFICATE-----"
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                />
                {errors.tls_cert && (
                  <p className="text-xs text-destructive mt-1">{errors.tls_cert.message}</p>
                )}
              </div>

              {/* Client Key */}
              <div>
                <label htmlFor="tls_key" className="block text-sm font-medium mb-1">
                  Client Private Key
                </label>
                <textarea
                  id="tls_key"
                  {...register('tls_key')}
                  rows={4}
                  placeholder="-----BEGIN PRIVATE KEY-----&#10;...&#10;-----END PRIVATE KEY-----"
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-mono"
                />
                {errors.tls_key && (
                  <p className="text-xs text-destructive mt-1">{errors.tls_key.message}</p>
                )}
              </div>
            </div>
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
            />
            {errors.description && (
              <p className="text-xs text-destructive mt-1">{errors.description.message}</p>
            )}
          </div>

          {/* Footer Actions */}
          <div className="flex justify-end gap-2 pt-4 border-t">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting
                ? 'Saving...'
                : host
                ? 'Update Host'
                : 'Add Host'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
