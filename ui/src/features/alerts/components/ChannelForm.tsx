/**
 * ChannelForm Component
 *
 * Form for creating and editing notification channels
 */

import { useState } from 'react'
import { NotificationChannel, ChannelCreateRequest } from '../hooks/useNotificationChannels'
import { Smartphone, Send, MessageSquare, Hash, Bell, Mail, Webhook } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

interface Props {
  channel?: NotificationChannel | null
  onSubmit: (data: ChannelCreateRequest) => void
  onCancel: () => void
  onTest?: (data: ChannelCreateRequest) => void
  isSubmitting?: boolean
  isTesting?: boolean
}

const CHANNEL_TYPES = [
  { value: 'telegram', label: 'Telegram', icon: Send },
  { value: 'discord', label: 'Discord', icon: MessageSquare },
  { value: 'slack', label: 'Slack', icon: Hash },
  { value: 'pushover', label: 'Pushover', icon: Smartphone },
  { value: 'gotify', label: 'Gotify', icon: Bell },
  { value: 'smtp', label: 'Email (SMTP)', icon: Mail },
  { value: 'webhook', label: 'Webhook', icon: Webhook },
]

export function ChannelForm({ channel, onSubmit, onCancel, onTest, isSubmitting, isTesting }: Props) {
  const isEditing = !!channel

  const [formData, setFormData] = useState<ChannelCreateRequest>({
    name: channel?.name || '',
    type: channel?.type || 'telegram',
    config: channel?.config || {},
    enabled: channel?.enabled ?? true,
  })

  const [errors, setErrors] = useState<Record<string, string>>({})

  const handleChange = (field: string, value: any) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
    // Clear error when user types
    if (errors[field]) {
      setErrors((prev) => {
        const newErrors = { ...prev }
        delete newErrors[field]
        return newErrors
      })
    }
  }

  const handleConfigChange = (field: string, value: any) => {
    setFormData((prev) => ({
      ...prev,
      config: { ...prev.config, [field]: value },
    }))
    // Clear error when user types
    if (errors[`config.${field}`]) {
      setErrors((prev) => {
        const newErrors = { ...prev }
        delete newErrors[`config.${field}`]
        return newErrors
      })
    }
  }

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {}

    if (!formData.name.trim()) {
      newErrors.name = 'Channel name is required'
    }

    // Type-specific validation
    switch (formData.type) {
      case 'telegram':
        if (!formData.config.bot_token && !formData.config.token) {
          newErrors['config.bot_token'] = 'Bot token is required'
        }
        if (!formData.config.chat_id) {
          newErrors['config.chat_id'] = 'Chat ID is required'
        }
        break
      case 'discord':
      case 'slack':
        if (!formData.config.webhook_url) {
          newErrors['config.webhook_url'] = 'Webhook URL is required'
        }
        break
      case 'pushover':
        if (!formData.config.app_token) {
          newErrors['config.app_token'] = 'App token is required'
        }
        if (!formData.config.user_key) {
          newErrors['config.user_key'] = 'User key is required'
        }
        break
      case 'gotify':
        if (!formData.config.server_url) {
          newErrors['config.server_url'] = 'Server URL is required'
        }
        if (!formData.config.app_token) {
          newErrors['config.app_token'] = 'App token is required'
        }
        break
      case 'smtp':
        if (!formData.config.smtp_host) {
          newErrors['config.smtp_host'] = 'SMTP host is required'
        }
        if (!formData.config.smtp_user) {
          newErrors['config.smtp_user'] = 'SMTP user is required'
        }
        if (!formData.config.smtp_password) {
          newErrors['config.smtp_password'] = 'SMTP password is required'
        }
        if (!formData.config.from_email) {
          newErrors['config.from_email'] = 'From email is required'
        }
        if (!formData.config.to_email) {
          newErrors['config.to_email'] = 'To email is required'
        }
        break
      case 'webhook':
        if (!formData.config.url) {
          newErrors['config.url'] = 'Webhook URL is required'
        } else if (!formData.config.url.startsWith('http://') && !formData.config.url.startsWith('https://')) {
          newErrors['config.url'] = 'URL must start with http:// or https://'
        }
        break
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (validate()) {
      onSubmit(formData)
    }
  }

  const handleTestClick = () => {
    if (validate() && onTest) {
      onTest(formData)
    }
  }

  const selectedType = CHANNEL_TYPES.find((t) => t.value === formData.type)
  const IconComponent = selectedType?.icon || Bell

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {/* Basic Info */}
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">Channel Name *</label>
          <input
            type="text"
            value={formData.name}
            onChange={(e) => handleChange('name', e.target.value)}
            placeholder="e.g., Production Alerts"
            className={`w-full rounded-md border ${errors.name ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
          />
          {errors.name && <p className="mt-1 text-xs text-red-400">{errors.name}</p>}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">Channel Type *</label>
          <Select
            value={formData.type}
            onValueChange={(value) => {
              handleChange('type', value)
              handleChange('config', {}) // Reset config when type changes
            }}
            disabled={isEditing}
          >
            <SelectTrigger>
              <SelectValue>
                {CHANNEL_TYPES.find((t) => t.value === formData.type)?.label}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {CHANNEL_TYPES.map((type) => {
                const IconComponent = type.icon
                return (
                  <SelectItem key={type.value} value={type.value}>
                    <div className="flex items-center gap-2">
                      <IconComponent className="h-4 w-4" />
                      <span>{type.label}</span>
                    </div>
                  </SelectItem>
                )
              })}
            </SelectContent>
          </Select>
          {isEditing && (
            <p className="mt-1 text-xs text-gray-400">Channel type cannot be changed after creation</p>
          )}
        </div>
      </div>

      {/* Type-Specific Configuration */}
      <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
        <div className="flex items-center gap-2 mb-2">
          <IconComponent className="h-5 w-5 text-gray-400" />
          <h3 className="text-sm font-semibold text-white">{selectedType?.label} Configuration</h3>
        </div>

        {formData.type === 'telegram' && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Bot Token *</label>
              <input
                type="text"
                value={formData.config.bot_token || formData.config.token || ''}
                onChange={(e) => handleConfigChange('bot_token', e.target.value)}
                placeholder="123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
                className={`w-full rounded-md border ${errors['config.bot_token'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
              />
              {errors['config.bot_token'] && <p className="mt-1 text-xs text-red-400">{errors['config.bot_token']}</p>}
              <p className="mt-1 text-xs text-gray-400">Get from @BotFather on Telegram</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Chat ID *</label>
              <input
                type="text"
                value={formData.config.chat_id || ''}
                onChange={(e) => handleConfigChange('chat_id', e.target.value)}
                placeholder="-1001234567890"
                className={`w-full rounded-md border ${errors['config.chat_id'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
              />
              {errors['config.chat_id'] && <p className="mt-1 text-xs text-red-400">{errors['config.chat_id']}</p>}
              <p className="mt-1 text-xs text-gray-400">Use @userinfobot to get your chat ID</p>
            </div>
          </>
        )}

        {(formData.type === 'discord' || formData.type === 'slack') && (
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Webhook URL *</label>
            <input
              type="url"
              value={formData.config.webhook_url || ''}
              onChange={(e) => handleConfigChange('webhook_url', e.target.value)}
              placeholder={formData.type === 'discord' ? 'https://discord.com/api/webhooks/...' : 'https://hooks.slack.com/services/...'}
              className={`w-full rounded-md border ${errors['config.webhook_url'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
            />
            {errors['config.webhook_url'] && <p className="mt-1 text-xs text-red-400">{errors['config.webhook_url']}</p>}
            <p className="mt-1 text-xs text-gray-400">
              {formData.type === 'discord' ? 'Server Settings → Integrations → Webhooks' : 'Create Incoming Webhook in Slack'}
            </p>
          </div>
        )}

        {formData.type === 'pushover' && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">App Token *</label>
              <input
                type="text"
                value={formData.config.app_token || ''}
                onChange={(e) => handleConfigChange('app_token', e.target.value)}
                placeholder="azGDORePK8gMaC0QOYAMyEEuzJnyUi"
                className={`w-full rounded-md border ${errors['config.app_token'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
              />
              {errors['config.app_token'] && <p className="mt-1 text-xs text-red-400">{errors['config.app_token']}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">User Key *</label>
              <input
                type="text"
                value={formData.config.user_key || ''}
                onChange={(e) => handleConfigChange('user_key', e.target.value)}
                placeholder="uQiRzpo4DXghDmr9QzzfQu27cmVRsG"
                className={`w-full rounded-md border ${errors['config.user_key'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
              />
              {errors['config.user_key'] && <p className="mt-1 text-xs text-red-400">{errors['config.user_key']}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">DockMon URL (optional)</label>
              <input
                type="url"
                value={formData.config.url || ''}
                onChange={(e) => handleConfigChange('url', e.target.value)}
                placeholder="https://dockmon.example.com"
                className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <p className="mt-1 text-xs text-gray-400">Link to open in notifications</p>
            </div>
          </>
        )}

        {formData.type === 'gotify' && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Server URL *</label>
              <input
                type="url"
                value={formData.config.server_url || ''}
                onChange={(e) => handleConfigChange('server_url', e.target.value)}
                placeholder="https://gotify.example.com"
                className={`w-full rounded-md border ${errors['config.server_url'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
              />
              {errors['config.server_url'] && <p className="mt-1 text-xs text-red-400">{errors['config.server_url']}</p>}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">App Token *</label>
              <input
                type="text"
                value={formData.config.app_token || ''}
                onChange={(e) => handleConfigChange('app_token', e.target.value)}
                placeholder="A.fKy2xqLpNm..."
                className={`w-full rounded-md border ${errors['config.app_token'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
              />
              {errors['config.app_token'] && <p className="mt-1 text-xs text-red-400">{errors['config.app_token']}</p>}
              <p className="mt-1 text-xs text-gray-400">Create an app in Gotify to get token</p>
            </div>
          </>
        )}

        {formData.type === 'smtp' && (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">SMTP Host *</label>
                <input
                  type="text"
                  value={formData.config.smtp_host || ''}
                  onChange={(e) => handleConfigChange('smtp_host', e.target.value)}
                  placeholder="smtp.gmail.com"
                  className={`w-full rounded-md border ${errors['config.smtp_host'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
                />
                {errors['config.smtp_host'] && <p className="mt-1 text-xs text-red-400">{errors['config.smtp_host']}</p>}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Port</label>
                <input
                  type="number"
                  value={formData.config.smtp_port || 587}
                  onChange={(e) => handleConfigChange('smtp_port', parseInt(e.target.value))}
                  placeholder="587"
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">SMTP User *</label>
                <input
                  type="text"
                  value={formData.config.smtp_user || ''}
                  onChange={(e) => handleConfigChange('smtp_user', e.target.value)}
                  placeholder="username@example.com"
                  className={`w-full rounded-md border ${errors['config.smtp_user'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
                />
                {errors['config.smtp_user'] && <p className="mt-1 text-xs text-red-400">{errors['config.smtp_user']}</p>}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">SMTP Password *</label>
                <input
                  type="password"
                  value={formData.config.smtp_password || ''}
                  onChange={(e) => handleConfigChange('smtp_password', e.target.value)}
                  placeholder="••••••••"
                  className={`w-full rounded-md border ${errors['config.smtp_password'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
                />
                {errors['config.smtp_password'] && <p className="mt-1 text-xs text-red-400">{errors['config.smtp_password']}</p>}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">From Email *</label>
                <input
                  type="email"
                  value={formData.config.from_email || ''}
                  onChange={(e) => handleConfigChange('from_email', e.target.value)}
                  placeholder="alerts@example.com"
                  className={`w-full rounded-md border ${errors['config.from_email'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
                />
                {errors['config.from_email'] && <p className="mt-1 text-xs text-red-400">{errors['config.from_email']}</p>}
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">To Email *</label>
                <input
                  type="email"
                  value={formData.config.to_email || ''}
                  onChange={(e) => handleConfigChange('to_email', e.target.value)}
                  placeholder="admin@example.com"
                  className={`w-full rounded-md border ${errors['config.to_email'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
                />
                {errors['config.to_email'] && <p className="mt-1 text-xs text-red-400">{errors['config.to_email']}</p>}
              </div>
            </div>
            <div>
              <label className="flex items-center gap-2 text-sm text-gray-300">
                <input
                  type="checkbox"
                  checked={formData.config.use_tls ?? true}
                  onChange={(e) => handleConfigChange('use_tls', e.target.checked)}
                  className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0"
                />
                Use TLS/SSL (recommended)
              </label>
            </div>
          </>
        )}

        {formData.type === 'webhook' && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Webhook URL *</label>
              <input
                type="url"
                value={formData.config.url || ''}
                onChange={(e) => handleConfigChange('url', e.target.value)}
                placeholder="https://your-service.com/webhook"
                className={`w-full rounded-md border ${errors['config.url'] ? 'border-red-500' : 'border-gray-700'} bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500`}
              />
              {errors['config.url'] && <p className="mt-1 text-xs text-red-400">{errors['config.url']}</p>}
              <p className="mt-1 text-xs text-gray-400">HTTPS recommended for production</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">HTTP Method</label>
              <Select
                value={formData.config.method || 'POST'}
                onValueChange={(value) => handleConfigChange('method', value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="POST">POST</SelectItem>
                  <SelectItem value="PUT">PUT</SelectItem>
                </SelectContent>
              </Select>
              <p className="mt-1 text-xs text-gray-400">HTTP method for webhook requests</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Payload Format</label>
              <Select
                value={formData.config.payload_format || 'json'}
                onValueChange={(value) => handleConfigChange('payload_format', value)}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="json">JSON</SelectItem>
                  <SelectItem value="form">Form-encoded</SelectItem>
                </SelectContent>
              </Select>
              <p className="mt-1 text-xs text-gray-400">Format of the webhook payload</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Custom Headers (JSON, optional)</label>
              <textarea
                value={typeof formData.config.headers === 'string' ? formData.config.headers : JSON.stringify(formData.config.headers || {}, null, 2)}
                onChange={(e) => {
                  try {
                    const parsed = JSON.parse(e.target.value)
                    handleConfigChange('headers', parsed)
                  } catch {
                    // Allow invalid JSON while typing
                    handleConfigChange('headers', e.target.value)
                  }
                }}
                placeholder={'{\n  "Authorization": "Bearer token",\n  "X-Custom-Header": "value"\n}'}
                rows={4}
                className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <p className="mt-1 text-xs text-gray-400">Add custom HTTP headers (e.g., Authorization)</p>
            </div>
          </>
        )}
      </div>

      {/* Enable/Disable */}
      <div>
        <label className="flex items-center gap-2 text-sm text-gray-300">
          <input
            type="checkbox"
            checked={formData.enabled}
            onChange={(e) => handleChange('enabled', e.target.checked)}
            className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0"
          />
          Enable this channel
        </label>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-end gap-3 pt-4 border-t border-gray-700">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md bg-gray-800 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-700"
        >
          Cancel
        </button>
        {onTest && (
          <button
            type="button"
            onClick={handleTestClick}
            disabled={isTesting}
            className="rounded-md bg-gray-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-600 disabled:opacity-50"
          >
            {isTesting ? 'Testing...' : 'Test Configuration'}
          </button>
        )}
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
        >
          {isSubmitting ? 'Saving...' : isEditing ? 'Update Channel' : 'Create Channel'}
        </button>
      </div>
    </form>
  )
}
