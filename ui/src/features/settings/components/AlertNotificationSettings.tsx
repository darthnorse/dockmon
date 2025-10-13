/**
 * Alert & Notification Settings Component
 * Customize alert message templates
 */

import { useState } from 'react'
import { useGlobalSettings, useUpdateGlobalSettings, useTemplateVariables } from '@/hooks/useSettings'
import { toast } from 'sonner'
import { RotateCcw, Copy, Check } from 'lucide-react'

const DEFAULT_TEMPLATE = `🚨 **{SEVERITY} Alert: {KIND}**

**{SCOPE_TYPE}:** \`{CONTAINER_NAME}\`
**Host:** {HOST_NAME}
**Current Value:** {CURRENT_VALUE} (threshold: {THRESHOLD})
**Occurrences:** {OCCURRENCES}
**Time:** {TIMESTAMP}
**Rule:** {RULE_NAME}
───────────────────────`

export function AlertNotificationSettings() {
  const { data: settings } = useGlobalSettings()
  const { data: variables } = useTemplateVariables()
  const updateSettings = useUpdateGlobalSettings()

  const [template, setTemplate] = useState(settings?.alert_template || DEFAULT_TEMPLATE)
  const [copiedVar, setCopiedVar] = useState<string | null>(null)
  const [hasChanges, setHasChanges] = useState(false)

  // Update local state when settings load
  useState(() => {
    if (settings?.alert_template) {
      setTemplate(settings.alert_template)
    }
  })

  const handleTemplateChange = (value: string) => {
    setTemplate(value)
    setHasChanges(true)
  }

  const handleSave = async () => {
    try {
      await updateSettings.mutateAsync({ alert_template: template })
      setHasChanges(false)
      toast.success('Alert template saved successfully')
    } catch (error) {
      toast.error('Failed to save alert template')
    }
  }

  const handleReset = () => {
    setTemplate(DEFAULT_TEMPLATE)
    setHasChanges(true)
    toast.info('Template reset to default (click Save to apply)')
  }

  const handleCopyVariable = (variable: string) => {
    navigator.clipboard.writeText(variable)
    setCopiedVar(variable)
    setTimeout(() => setCopiedVar(null), 2000)
    toast.success('Variable copied to clipboard')
  }

  return (
    <div className="space-y-6">
      {/* Alert Message Template Section */}
      <div className="bg-surface border border-border rounded-lg p-6">
        <div className="mb-4">
          <h2 className="text-lg font-semibold">Alert Message Template</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Customize the message format for all alert notifications. Use variables to insert dynamic values.
          </p>
        </div>

        <div className="space-y-4">
          {/* Template Editor */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">Message Template</label>
            <textarea
              value={template}
              onChange={(e) => handleTemplateChange(e.target.value)}
              rows={12}
              className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white font-mono text-sm placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="Enter your custom alert template..."
            />
            <p className="mt-2 text-xs text-gray-400">
              Supports markdown formatting. Use variables like {'{CONTAINER_NAME}'} for dynamic content.
            </p>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleSave}
              disabled={!hasChanges || updateSettings.isPending}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {updateSettings.isPending ? 'Saving...' : 'Save Template'}
            </button>
            <button
              onClick={handleReset}
              className="flex items-center gap-2 rounded-md bg-gray-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-600"
            >
              <RotateCcw className="h-4 w-4" />
              Reset to Default
            </button>
          </div>
        </div>
      </div>

      {/* Available Variables Section */}
      <div className="bg-surface border border-border rounded-lg p-6">
        <div className="mb-4">
          <h2 className="text-lg font-semibold">Available Variables</h2>
          <p className="text-sm text-muted-foreground mt-1">
            Click to copy a variable to your clipboard
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {variables?.variables.map((info) => (
            <button
              key={info.name}
              onClick={() => handleCopyVariable(info.name)}
              className="flex items-start gap-3 p-3 rounded-md bg-gray-800/50 border border-gray-700 hover:bg-gray-800 hover:border-gray-600 transition-colors text-left"
            >
              <div className="flex-shrink-0 mt-0.5">
                {copiedVar === info.name ? (
                  <Check className="h-4 w-4 text-green-400" />
                ) : (
                  <Copy className="h-4 w-4 text-gray-400" />
                )}
              </div>
              <div className="flex-1 min-w-0">
                <code className="text-sm font-mono text-blue-400 break-all">{info.name}</code>
                <p className="text-xs text-gray-400 mt-1">{info.description}</p>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
