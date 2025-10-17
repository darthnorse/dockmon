/**
 * Alert Template Settings Component
 * Customize alert message templates with category-specific options
 */

import { useState, useEffect } from 'react'
import { useGlobalSettings, useUpdateGlobalSettings, useTemplateVariables } from '@/hooks/useSettings'
import { toast } from 'sonner'
import { RotateCcw, Copy, Check } from 'lucide-react'

type TemplateType = 'default' | 'metric' | 'state_change' | 'health' | 'update'

export function AlertTemplateSettings() {
  const { data: settings } = useGlobalSettings()
  const { data: variables } = useTemplateVariables()
  const updateSettings = useUpdateGlobalSettings()

  const [activeTab, setActiveTab] = useState<TemplateType>('default')
  const [templates, setTemplates] = useState<Record<TemplateType, string>>({
    default: '',
    metric: '',
    state_change: '',
    health: '',
    update: '',
  })
  const [copiedVar, setCopiedVar] = useState<string | null>(null)
  const [hasChanges, setHasChanges] = useState(false)

  // Load templates from settings OR backend defaults
  useEffect(() => {
    if (settings && variables?.default_templates) {
      setTemplates({
        default: settings.alert_template || variables.default_templates.default,
        metric: settings.alert_template_metric || variables.default_templates.metric,
        state_change: settings.alert_template_state_change || variables.default_templates.state_change,
        health: settings.alert_template_health || variables.default_templates.health,
        update: settings.alert_template_update || variables.default_templates.update,
      })
    }
  }, [settings, variables])

  const handleTemplateChange = (type: TemplateType, value: string) => {
    setTemplates(prev => ({ ...prev, [type]: value }))
    setHasChanges(true)
  }

  const handleSave = async () => {
    try {
      await updateSettings.mutateAsync({
        alert_template: templates.default,
        alert_template_metric: templates.metric,
        alert_template_state_change: templates.state_change,
        alert_template_health: templates.health,
        alert_template_update: templates.update,
      })
      setHasChanges(false)
      toast.success('Alert templates saved successfully')
    } catch (error) {
      toast.error('Failed to save alert templates')
    }
  }

  const handleReset = (type: TemplateType) => {
    if (variables?.default_templates) {
      setTemplates(prev => ({ ...prev, [type]: variables.default_templates[type] }))
      setHasChanges(true)
      toast.info(`${type === 'default' ? 'Default' : type.replace('_', ' ')} template reset (click Save to apply)`)
    }
  }

  const handleResetAll = () => {
    if (variables?.default_templates) {
      setTemplates(variables.default_templates)
      setHasChanges(true)
      toast.info('All templates reset to default (click Save to apply)')
    }
  }

  const handleCopyVariable = (variable: string) => {
    navigator.clipboard.writeText(variable)
    setCopiedVar(variable)
    setTimeout(() => setCopiedVar(null), 2000)
    toast.success('Variable copied to clipboard')
  }

  const tabs = [
    { id: 'default' as TemplateType, label: 'Default', description: 'Fallback for all alerts' },
    { id: 'metric' as TemplateType, label: 'Metric Alerts', description: 'CPU, Memory, Disk usage' },
    { id: 'state_change' as TemplateType, label: 'State Changes', description: 'Stopped, Died, Restarted' },
    { id: 'health' as TemplateType, label: 'Health Checks', description: 'Unhealthy status' },
    { id: 'update' as TemplateType, label: 'Container Updates', description: 'Update available' },
  ]

  return (
    <div className="space-y-6">
      {/* Template Category Tabs */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Template Categories</h3>
          <p className="text-xs text-gray-400 mt-1">
            Customize message format for different alert types. Rules without a custom template use these.
          </p>
        </div>

        <div className="flex gap-2 overflow-x-auto pb-2">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-shrink-0 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              <div className="text-left">
                <div>{tab.label}</div>
                <div className="text-xs opacity-75">{tab.description}</div>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Template Editor */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <label className="block text-sm font-medium text-gray-300">
            {tabs.find(t => t.id === activeTab)?.label} Template
          </label>
          <button
            onClick={() => handleReset(activeTab)}
            className="text-xs text-blue-400 hover:text-blue-300 underline"
          >
            Reset this template
          </button>
        </div>
        <textarea
          value={templates[activeTab]}
          onChange={(e) => handleTemplateChange(activeTab, e.target.value)}
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
          {updateSettings.isPending ? 'Saving...' : 'Save All Templates'}
        </button>
        <button
          onClick={handleResetAll}
          className="flex items-center gap-2 rounded-md bg-gray-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-600"
        >
          <RotateCcw className="h-4 w-4" />
          Reset All to Default
        </button>
      </div>

      {/* Available Variables */}
      <div>
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-white">Available Variables</h3>
          <p className="text-xs text-gray-400 mt-1">
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
