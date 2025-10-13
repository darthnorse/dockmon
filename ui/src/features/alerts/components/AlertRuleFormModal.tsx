/**
 * AlertRuleFormModal Component
 *
 * Form for creating and editing alert rules
 */

import { useState, useRef, useEffect } from 'react'
import { X, Search, Check, Bell, Send, MessageSquare, Hash, Smartphone, Mail } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useCreateAlertRule, useUpdateAlertRule } from '../hooks/useAlertRules'
import type { AlertRule, AlertSeverity, AlertScope } from '@/types/alerts'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import type { Host } from '@/types/api'
import type { Container } from '@/features/containers/types'
import { apiClient } from '@/lib/api/client'

interface Props {
  rule?: AlertRule | null
  onClose: () => void
}

const RULE_KINDS = [
  {
    value: 'cpu_high',
    label: 'High CPU Usage',
    description: 'Alert when CPU usage exceeds threshold',
    requiresMetric: true,
    metric: 'cpu_percent',
    defaultOperator: '>=',
    defaultThreshold: 90,
    scopes: ['host', 'container', 'group']
  },
  {
    value: 'memory_high',
    label: 'High Memory Usage',
    description: 'Alert when memory usage exceeds threshold',
    requiresMetric: true,
    metric: 'memory_percent',
    defaultOperator: '>=',
    defaultThreshold: 90,
    scopes: ['host', 'container', 'group']
  },
  {
    value: 'disk_low',
    label: 'Low Disk Space',
    description: 'Alert when disk usage exceeds threshold',
    requiresMetric: true,
    metric: 'disk_percent',
    defaultOperator: '>=',
    defaultThreshold: 85,
    scopes: ['host']
  },
  {
    value: 'container_unhealthy',
    label: 'Container Health Check Failing',
    description: 'Alert when container health check fails (requires health check configured)',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'container_died',
    label: 'Container Died/Crashed',
    description: 'Alert when container exits unexpectedly (non-zero exit code, OOM, crash)',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'container_stopped',
    label: 'Container Stopped',
    description: 'Alert when container is stopped (exit code 0 - normal shutdown)',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'container_restart',
    label: 'Container Restarted',
    description: 'Alert when container restarts (any restart, expected or unexpected)',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'host_down',
    label: 'Host Offline',
    description: 'Alert when host becomes unreachable',
    requiresMetric: false,
    scopes: ['host']
  },
]

const OPERATORS = [
  { value: '>=', label: '>= (Greater than or equal)' },
  { value: '<=', label: '<= (Less than or equal)' },
  { value: '>', label: '> (Greater than)' },
  { value: '<', label: '< (Less than)' },
]

const NOTIFICATION_CHANNELS = [
  { value: 'pushover', label: 'Pushover', icon: Smartphone },
  { value: 'telegram', label: 'Telegram', icon: Send },
  { value: 'discord', label: 'Discord', icon: MessageSquare },
  { value: 'slack', label: 'Slack', icon: Hash },
  { value: 'gotify', label: 'Gotify', icon: Bell },
  { value: 'smtp', label: 'Email (SMTP)', icon: Mail },
]

export function AlertRuleFormModal({ rule, onClose }: Props) {
  const createRule = useCreateAlertRule()
  const updateRule = useUpdateAlertRule()
  const isEditing = !!rule

  // Fetch hosts and containers for selectors
  const { data: hostsData } = useHosts()
  const { data: containersData } = useQuery<Container[]>({
    queryKey: ['containers'],
    queryFn: () => apiClient.get('/containers'),
  })

  // Fetch configured notification channels
  const { data: channelsData } = useQuery<{ channels: Array<{ id: number; type: string; name: string; enabled: boolean }> }>({
    queryKey: ['notification-channels'],
    queryFn: () => apiClient.get('/notifications/channels'),
  })

  const hosts: Host[] = hostsData || []
  const containers: Container[] = containersData || []
  const configuredChannels = channelsData?.channels || []

  // Parse existing selectors
  const parseSelector = (json: string | null | undefined) => {
    if (!json) return { all: true, selected: [] }
    try {
      const parsed = JSON.parse(json)
      if (parsed.include_all) return { all: true, selected: [] }
      if (parsed.include) return { all: false, selected: parsed.include }
      return { all: true, selected: [] }
    } catch {
      return { all: true, selected: [] }
    }
  }

  const [formData, setFormData] = useState<any>({
    name: rule?.name || '',
    description: rule?.description || '',
    scope: rule?.scope || 'container',
    kind: rule?.kind || 'cpu_high',
    enabled: rule?.enabled ?? true,
    severity: rule?.severity || 'warning',
    metric: rule?.metric || 'cpu_percent',
    threshold: rule?.threshold || 90,
    operator: rule?.operator || '>=',
    duration_seconds: rule?.duration_seconds || 300,
    occurrences: rule?.occurrences || 3,
    clear_threshold: rule?.clear_threshold,
    clear_duration_seconds: rule?.clear_duration_seconds,
    grace_seconds: rule?.grace_seconds || 0,
    cooldown_seconds: rule?.cooldown_seconds || 300,
    // Selectors
    host_selector_all: parseSelector(rule?.host_selector_json).all,
    host_selector_ids: parseSelector(rule?.host_selector_json).selected,
    container_selector_all: parseSelector(rule?.container_selector_json).all,
    container_selector_names: parseSelector(rule?.container_selector_json).selected,
    notify_channels: rule?.notify_channels_json ? JSON.parse(rule.notify_channels_json) : [],
  })

  const [error, setError] = useState<string | null>(null)

  // Host/Container dropdown state
  const [hostSearchInput, setHostSearchInput] = useState('')
  const [showHostDropdown, setShowHostDropdown] = useState(false)
  const hostDropdownRef = useRef<HTMLDivElement>(null)
  const [containerSearchInput, setContainerSearchInput] = useState('')
  const [showContainerDropdown, setShowContainerDropdown] = useState(false)
  const containerDropdownRef = useRef<HTMLDivElement>(null)

  // Tag selector state for group scope
  const [tagSearchInput, setTagSearchInput] = useState('')
  const [availableTags, setAvailableTags] = useState<string[]>([])
  const [selectedTags, setSelectedTags] = useState<string[]>(() => {
    // Initialize with existing tags if editing
    if (rule?.labels_json) {
      try {
        const parsed = JSON.parse(rule.labels_json)
        return parsed.tags || []
      } catch {
        return []
      }
    }
    return []
  })

  // Fetch available tags for group scope
  useEffect(() => {
    const fetchTags = async () => {
      try {
        const res = await fetch(`/api/tags/suggest?q=${tagSearchInput}&limit=50`)
        const data = await res.json()
        // Tags API returns objects like {id, name, color, kind}, extract just the names
        const tagNames = Array.isArray(data.tags)
          ? data.tags.map((t: any) => typeof t === 'string' ? t : t.name)
          : []
        setAvailableTags(tagNames)
      } catch (err) {
        console.error('Failed to fetch tags:', err)
      }
    }

    if (formData.scope === 'group') {
      fetchTags()
    }
  }, [tagSearchInput, formData.scope])

  const selectedKind = RULE_KINDS.find((k) => k.value === formData.kind)
  const requiresMetric = selectedKind?.requiresMetric ?? true

  // Filter rule kinds based on selected scope
  const availableRuleKinds = RULE_KINDS.filter((k) => k.scopes.includes(formData.scope))

  // Filter hosts/containers based on search
  const filteredHosts = hosts.filter(
    (h) =>
      h.name.toLowerCase().includes(hostSearchInput.toLowerCase()) ||
      (h.url && h.url.toLowerCase().includes(hostSearchInput.toLowerCase()))
  )

  const filteredContainers = containers.filter((c) =>
    c.name.toLowerCase().includes(containerSearchInput.toLowerCase()) ||
    (c.host_name && c.host_name.toLowerCase().includes(containerSearchInput.toLowerCase()))
  )

  // Close dropdowns when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (hostDropdownRef.current && !hostDropdownRef.current.contains(event.target as Node)) {
        setShowHostDropdown(false)
      }
      if (containerDropdownRef.current && !containerDropdownRef.current.contains(event.target as Node)) {
        setShowContainerDropdown(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    try {
      // Prepare request data
      const requestData: any = {
        name: formData.name,
        description: formData.description,
        scope: formData.scope,
        kind: formData.kind,
        enabled: formData.enabled,
        severity: formData.severity,
        grace_seconds: formData.grace_seconds,
        cooldown_seconds: formData.cooldown_seconds,
      }

      // Add metric fields only if required
      if (requiresMetric) {
        requestData.metric = formData.metric
        requestData.threshold = formData.threshold
        requestData.operator = formData.operator
        requestData.duration_seconds = formData.duration_seconds
        requestData.occurrences = formData.occurrences
        if (formData.clear_threshold !== undefined) {
          requestData.clear_threshold = formData.clear_threshold
        }
        if (formData.clear_duration_seconds !== undefined) {
          requestData.clear_duration_seconds = formData.clear_duration_seconds
        }
      }

      // Add selectors
      if (formData.host_selector_all) {
        requestData.host_selector_json = JSON.stringify({ include_all: true })
      } else if (formData.host_selector_ids.length > 0) {
        requestData.host_selector_json = JSON.stringify({ include: formData.host_selector_ids })
      }

      if (formData.container_selector_all) {
        requestData.container_selector_json = JSON.stringify({ include_all: true })
      } else if (formData.container_selector_names.length > 0) {
        requestData.container_selector_json = JSON.stringify({ include: formData.container_selector_names })
      }

      // Add notification channels
      if (formData.notify_channels.length > 0) {
        requestData.notify_channels_json = JSON.stringify(formData.notify_channels)
      }

      // Add group tags (labels_json) for group scope
      if (formData.scope === 'group' && selectedTags.length > 0) {
        requestData.labels_json = JSON.stringify({ tags: selectedTags })
      }

      if (isEditing && rule) {
        await updateRule.mutateAsync({ ruleId: rule.id, rule: requestData })
      } else {
        await createRule.mutateAsync(requestData)
      }
      onClose()
    } catch (err: any) {
      setError(err.message || 'Failed to save rule')
    }
  }

  const handleChange = (field: string, value: any) => {
    setFormData((prev: any) => {
      const updated = { ...prev, [field]: value }

      // When scope changes, reset rule kind if current selection is invalid for new scope
      if (field === 'scope') {
        const currentKind = RULE_KINDS.find((k) => k.value === prev.kind)
        if (currentKind && !currentKind.scopes.includes(value)) {
          // Find first valid rule kind for new scope
          const firstValidKind = RULE_KINDS.find((k) => k.scopes.includes(value))
          if (firstValidKind) {
            updated.kind = firstValidKind.value
            if (firstValidKind.requiresMetric) {
              updated.metric = firstValidKind.metric
              updated.operator = firstValidKind.defaultOperator
              updated.threshold = firstValidKind.defaultThreshold
            }
          }
        }
      }

      // Auto-set metric, operator, and threshold when rule kind changes
      if (field === 'kind') {
        const kind = RULE_KINDS.find((k) => k.value === value)
        if (kind?.requiresMetric) {
          updated.metric = kind.metric
          updated.operator = kind.defaultOperator
          updated.threshold = kind.defaultThreshold
        }
      }

      return updated
    })
  }

  // Helper to build summary text
  const getSummaryText = () => {
    const parts: string[] = []

    // Trigger type
    if (requiresMetric) {
      const metricName = formData.metric?.replace('_', ' ')
      parts.push(`Trigger: ${metricName || 'metric'}`)
      parts.push(`Threshold: ${formData.operator} ${formData.threshold}%`)
      parts.push(`Duration: ${formData.duration_seconds}s (${formData.occurrences} breaches)`)
    } else {
      const kindLabel = selectedKind?.label || formData.kind
      parts.push(`Trigger: ${kindLabel}`)
    }

    // Scope
    if (formData.scope === 'host') {
      if (formData.host_selector_all) {
        parts.push('Scope: All hosts')
      } else if (formData.host_selector_ids.length > 0) {
        parts.push(`Scope: ${formData.host_selector_ids.length} selected host${formData.host_selector_ids.length > 1 ? 's' : ''}`)
      }
    } else if (formData.scope === 'container') {
      if (formData.container_selector_all) {
        parts.push('Scope: All containers')
      } else if (formData.container_selector_names.length > 0) {
        parts.push(`Scope: ${formData.container_selector_names.length} selected container${formData.container_selector_names.length > 1 ? 's' : ''}`)
      }
    } else if (formData.scope === 'group') {
      if (selectedTags.length > 0) {
        parts.push(`Scope: Group with tags [${selectedTags.join(', ')}]`)
      } else {
        parts.push('Scope: Group (no tags selected)')
      }
    } else {
      parts.push(`Scope: ${formData.scope}`)
    }

    // Severity
    parts.push(`Severity: ${formData.severity}`)

    // Notifications
    if (formData.notify_channels.length > 0) {
      const channelNames = formData.notify_channels
        .map((ch: string) => NOTIFICATION_CHANNELS.find(c => c.value === ch)?.label || ch)
        .join(', ')
      parts.push(`Notifications: ${channelNames}`)
    } else {
      parts.push('Notifications: None')
    }

    return parts
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-6xl rounded-lg border border-gray-700 bg-[#0d1117] shadow-2xl max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-700 px-6 py-4">
          <h2 className="text-xl font-semibold text-white">{isEditing ? 'Edit Alert Rule' : 'Create Alert Rule'}</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form - 2 Column Layout */}
        <form onSubmit={handleSubmit} className="flex">
          {/* Left Column - Form Fields */}
          <div className="flex-1 p-6 space-y-6 border-r border-gray-700">
            {error && (
              <div className="rounded-md bg-red-500/10 border border-red-500/20 px-4 py-3 text-sm text-red-400">
                {error}
              </div>
            )}

          {/* Basic Info */}
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Rule Name *</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => handleChange('name', e.target.value)}
                required
                className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                placeholder="e.g., High CPU Alert"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1">Description</label>
              <textarea
                value={formData.description}
                onChange={(e) => handleChange('description', e.target.value)}
                rows={2}
                className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                placeholder="Optional description of what this rule monitors"
              />
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Scope *</label>
                <select
                  value={formData.scope}
                  onChange={(e) => handleChange('scope', e.target.value as AlertScope)}
                  required
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="host">Host</option>
                  <option value="container">Container</option>
                  <option value="group">Group</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Severity *</label>
                <select
                  value={formData.severity}
                  onChange={(e) => handleChange('severity', e.target.value as AlertSeverity)}
                  required
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  <option value="info">Info</option>
                  <option value="warning">Warning</option>
                  <option value="error">Error</option>
                  <option value="critical">Critical</option>
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Rule Type *</label>
                <select
                  value={formData.kind}
                  onChange={(e) => handleChange('kind', e.target.value)}
                  required
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  {availableRuleKinds.map((kind) => (
                    <option key={kind.value} value={kind.value}>
                      {kind.label}
                    </option>
                  ))}
                </select>
                {selectedKind?.description && (
                  <p className="mt-1 text-xs text-gray-400">{selectedKind.description}</p>
                )}
              </div>
            </div>
          </div>

          {/* Tag Selector (for group scope) */}
          {formData.scope === 'group' && (
            <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
              <h3 className="text-sm font-semibold text-white">Group Selection</h3>
              <p className="text-xs text-gray-400">Select which tags define this group (hosts/containers matching ANY of these tags)</p>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">Search and Select Tags</label>
                <div className="relative mb-2">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                  <input
                    type="text"
                    value={tagSearchInput}
                    onChange={(e) => setTagSearchInput(e.target.value)}
                    placeholder="Search tags..."
                    className="w-full pl-9 pr-3 py-2 rounded-md border border-gray-700 bg-gray-800 text-white placeholder-gray-500 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>

                {/* Available Tags */}
                <div className="space-y-1 max-h-40 overflow-y-auto border border-gray-700 rounded-md p-2 bg-gray-900">
                  {availableTags.length === 0 ? (
                    <div className="text-sm text-gray-400 text-center py-2">No tags found</div>
                  ) : (
                    availableTags.map((tag) => {
                      const isSelected = selectedTags.includes(tag)
                      return (
                        <button
                          key={tag}
                          type="button"
                          onClick={() => {
                            const newTags = isSelected
                              ? selectedTags.filter((t) => t !== tag)
                              : [...selectedTags, tag]
                            setSelectedTags(newTags)
                          }}
                          className="w-full px-3 py-1.5 text-left text-sm flex items-center gap-2 hover:bg-gray-800 rounded transition-colors"
                        >
                          <div
                            className={`h-4 w-4 rounded border flex items-center justify-center ${
                              isSelected
                                ? 'bg-blue-600 border-blue-600'
                                : 'border-gray-600 bg-gray-800'
                            }`}
                          >
                            {isSelected && <Check className="h-3 w-3 text-white" />}
                          </div>
                          <span className="text-white">{tag}</span>
                        </button>
                      )
                    })
                  )}
                </div>

                {/* Selected Tags Display */}
                {selectedTags.length > 0 && (
                  <div className="mt-3">
                    <label className="block text-xs font-medium text-gray-400 mb-2">Selected Tags ({selectedTags.length})</label>
                    <div className="flex flex-wrap gap-2">
                      {selectedTags.map((tag) => (
                        <span
                          key={tag}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-blue-600/20 text-blue-400 text-xs"
                        >
                          {tag}
                          <button
                            type="button"
                            onClick={() => setSelectedTags(selectedTags.filter((t) => t !== tag))}
                            className="hover:text-blue-300"
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Metric Conditions (only for metric-based rules) */}
          {requiresMetric && (
            <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
              <h3 className="text-sm font-semibold text-white">Threshold Configuration</h3>

              <div className="grid grid-cols-2 gap-4">

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">Operator *</label>
                  <select
                    value={formData.operator}
                    onChange={(e) => handleChange('operator', e.target.value)}
                    required={requiresMetric}
                    className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  >
                    {OPERATORS.map((op) => (
                      <option key={op.value} value={op.value}>
                        {op.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">
                    Threshold (%) *
                  </label>
                  <input
                    type="number"
                    value={formData.threshold}
                    onChange={(e) => handleChange('threshold', parseFloat(e.target.value))}
                    required={requiresMetric}
                    min={0}
                    max={100}
                    step={0.1}
                    className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <p className="mt-1 text-xs text-gray-400">
                    Alert when {formData.metric?.replace('_', ' ')} {formData.operator} {formData.threshold}%
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">Clear Threshold</label>
                  <input
                    type="number"
                    value={formData.clear_threshold || ''}
                    onChange={(e) => handleChange('clear_threshold', e.target.value ? parseFloat(e.target.value) : undefined)}
                    min={0}
                    max={100}
                    step={0.1}
                    className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder="Optional"
                  />
                  <p className="mt-1 text-xs text-gray-500">Value to auto-resolve alert</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">Clear Duration (seconds)</label>
                  <input
                    type="number"
                    value={formData.clear_duration_seconds || ''}
                    onChange={(e) => handleChange('clear_duration_seconds', e.target.value ? parseInt(e.target.value) : undefined)}
                    min={0}
                    className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    placeholder="Optional"
                  />
                  <p className="mt-1 text-xs text-gray-500">How long below threshold before auto-resolve</p>
                </div>
              </div>
            </div>
          )}

          {/* Timing Configuration */}
          <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
            <h3 className="text-sm font-semibold text-white">Timing Configuration</h3>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Duration (seconds) *</label>
                <input
                  type="number"
                  value={formData.duration_seconds}
                  onChange={(e) => handleChange('duration_seconds', parseInt(e.target.value))}
                  required
                  min={1}
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <p className="mt-1 text-xs text-gray-500">How long condition must be true</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Occurrences *</label>
                <input
                  type="number"
                  value={formData.occurrences}
                  onChange={(e) => handleChange('occurrences', parseInt(e.target.value))}
                  required
                  min={1}
                  max={100}
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <p className="mt-1 text-xs text-gray-500">Breaches needed to trigger alert</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Grace Period (seconds)</label>
                <input
                  type="number"
                  value={formData.grace_seconds}
                  onChange={(e) => handleChange('grace_seconds', parseInt(e.target.value))}
                  min={0}
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <p className="mt-1 text-xs text-gray-500">Wait time before evaluating rule</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Cooldown (seconds) *</label>
                <input
                  type="number"
                  value={formData.cooldown_seconds}
                  onChange={(e) => handleChange('cooldown_seconds', parseInt(e.target.value))}
                  required
                  min={0}
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
                <p className="mt-1 text-xs text-gray-500">Min time between alert notifications</p>
              </div>
            </div>
          </div>

          {/* Host Selector (for host/group scope) */}
          {(formData.scope === 'host' || formData.scope === 'group') && (
            <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">Host Selection</h3>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      handleChange('host_selector_ids', [])
                      handleChange('host_selector_all', true)
                    }}
                    className="text-xs text-blue-400 hover:text-blue-300 underline"
                  >
                    Select All
                  </button>
                  <span className="text-gray-600">|</span>
                  <button
                    type="button"
                    onClick={() => {
                      handleChange('host_selector_ids', [])
                      handleChange('host_selector_all', false)
                    }}
                    className="text-xs text-blue-400 hover:text-blue-300 underline"
                  >
                    Deselect All
                  </button>
                </div>
              </div>

              <div ref={hostDropdownRef} className="relative">
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Select Hosts
                  {formData.host_selector_all && hosts.length > 0 && (
                    <span className="ml-2 text-xs text-blue-400">({hosts.length} hosts - all selected)</span>
                  )}
                  {!formData.host_selector_all && formData.host_selector_ids.length > 0 && (
                    <span className="ml-2 text-xs text-blue-400">({formData.host_selector_ids.length} selected)</span>
                  )}
                </label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                  <input
                    type="text"
                    value={hostSearchInput}
                    onChange={(e) => setHostSearchInput(e.target.value)}
                    onFocus={() => setShowHostDropdown(true)}
                    placeholder="Search hosts..."
                    className="w-full pl-9 pr-3 py-2 rounded-md border border-gray-700 bg-gray-800 text-white placeholder-gray-500 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>

                {/* Host Dropdown */}
                {showHostDropdown && (
                  <div className="absolute z-50 w-full mt-1 py-1 rounded-md border border-gray-700 bg-gray-800 shadow-lg max-h-[240px] overflow-y-auto">
                    {filteredHosts.length === 0 ? (
                      <div className="px-3 py-2 text-sm text-gray-400">No hosts found</div>
                    ) : (
                      filteredHosts.map((host: Host) => {
                        const isSelected = formData.host_selector_all || formData.host_selector_ids.includes(host.id)
                        return (
                          <button
                            key={host.id}
                            type="button"
                            onClick={() => {
                              if (formData.host_selector_all) {
                                // When "all" is selected, clicking means exclude this one
                                const allExcept = hosts.filter(h => h.id !== host.id).map(h => h.id)
                                handleChange('host_selector_ids', allExcept)
                                handleChange('host_selector_all', false)
                              } else {
                                const newIds = isSelected
                                  ? formData.host_selector_ids.filter((id: string) => id !== host.id)
                                  : [...formData.host_selector_ids, host.id]
                                handleChange('host_selector_ids', newIds)
                              }
                            }}
                            className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-gray-700 transition-colors"
                          >
                            <div
                              className={`h-4 w-4 rounded border flex items-center justify-center ${
                                isSelected
                                  ? 'bg-blue-600 border-blue-600'
                                  : 'border-gray-600 bg-gray-800'
                              }`}
                            >
                              {isSelected && <Check className="h-3 w-3 text-white" />}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="font-medium truncate text-white">{host.name}</div>
                              {host.url && (
                                <div className="text-xs text-gray-400 truncate">{host.url}</div>
                              )}
                            </div>
                          </button>
                        )
                      })
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Container Selector (for container scope) */}
          {formData.scope === 'container' && (
            <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">Container Selection</h3>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      handleChange('container_selector_names', [])
                      handleChange('container_selector_all', true)
                    }}
                    className="text-xs text-blue-400 hover:text-blue-300 underline"
                  >
                    Select All
                  </button>
                  <span className="text-gray-600">|</span>
                  <button
                    type="button"
                    onClick={() => {
                      handleChange('container_selector_names', [])
                      handleChange('container_selector_all', false)
                    }}
                    className="text-xs text-blue-400 hover:text-blue-300 underline"
                  >
                    Deselect All
                  </button>
                </div>
              </div>

              <div ref={containerDropdownRef} className="relative">
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Select Containers
                  {formData.container_selector_all && containers.length > 0 && (
                    <span className="ml-2 text-xs text-blue-400">({containers.length} containers - all selected)</span>
                  )}
                  {!formData.container_selector_all && formData.container_selector_names.length > 0 && (
                    <span className="ml-2 text-xs text-blue-400">({formData.container_selector_names.length} selected)</span>
                  )}
                </label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none" />
                  <input
                    type="text"
                    value={containerSearchInput}
                    onChange={(e) => setContainerSearchInput(e.target.value)}
                    onFocus={() => setShowContainerDropdown(true)}
                    placeholder="Search containers..."
                    className="w-full pl-9 pr-3 py-2 rounded-md border border-gray-700 bg-gray-800 text-white placeholder-gray-500 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                </div>

                {/* Container Dropdown */}
                {showContainerDropdown && (
                  <div className="absolute z-50 w-full mt-1 py-1 rounded-md border border-gray-700 bg-gray-800 shadow-lg max-h-[240px] overflow-y-auto">
                    {filteredContainers.length === 0 ? (
                      <div className="px-3 py-2 text-sm text-gray-400">No containers found</div>
                    ) : (
                      filteredContainers.map((container: Container) => {
                        const isSelected = formData.container_selector_all || formData.container_selector_names.includes(container.name)
                        return (
                          <button
                            key={container.id}
                            type="button"
                            onClick={() => {
                              if (formData.container_selector_all) {
                                // When "all" is selected, clicking means exclude this one
                                const allExcept = containers.filter(c => c.name !== container.name).map(c => c.name)
                                handleChange('container_selector_names', allExcept)
                                handleChange('container_selector_all', false)
                              } else {
                                const newNames = isSelected
                                  ? formData.container_selector_names.filter((n: string) => n !== container.name)
                                  : [...formData.container_selector_names, container.name]
                                handleChange('container_selector_names', newNames)
                              }
                            }}
                            className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-gray-700 transition-colors"
                          >
                            <div
                              className={`h-4 w-4 rounded border flex items-center justify-center ${
                                isSelected
                                  ? 'bg-blue-600 border-blue-600'
                                  : 'border-gray-600 bg-gray-800'
                              }`}
                            >
                              {isSelected && <Check className="h-3 w-3 text-white" />}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="font-medium truncate text-white">{container.name}</div>
                              {container.host_name && (
                                <div className="text-xs text-gray-400 truncate">{container.host_name}</div>
                              )}
                            </div>
                          </button>
                        )
                      })
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Notification Channels */}
          <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
            <h3 className="text-sm font-semibold text-white">Notification Channels</h3>
            <p className="text-xs text-gray-400">Select which channels to notify when this alert fires</p>

            {configuredChannels.length === 0 ? (
              <div className="text-sm text-gray-400 py-4 text-center">
                No notification channels configured. Configure channels in Settings to enable notifications.
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                {NOTIFICATION_CHANNELS.filter(channel =>
                  configuredChannels.some(cc => cc.type === channel.value)
                ).map((channel) => {
                  const IconComponent = channel.icon
                  const configuredChannel = configuredChannels.find(cc => cc.type === channel.value)
                  const isDisabled = configuredChannel && !configuredChannel.enabled

                  return (
                    <label
                      key={channel.value}
                      className={`flex items-center gap-2 text-sm p-2 rounded ${
                        isDisabled
                          ? 'text-gray-500 cursor-not-allowed'
                          : 'text-gray-300 hover:bg-gray-800/50 cursor-pointer'
                      }`}
                      title={isDisabled ? `${channel.label} is disabled` : undefined}
                    >
                      <input
                        type="checkbox"
                        checked={formData.notify_channels.includes(channel.value)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            handleChange('notify_channels', [...formData.notify_channels, channel.value])
                          } else {
                            handleChange('notify_channels', formData.notify_channels.filter((ch: string) => ch !== channel.value))
                          }
                        }}
                        disabled={isDisabled}
                        className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0 disabled:opacity-50 disabled:cursor-not-allowed"
                      />
                      <IconComponent className="h-4 w-4" />
                      <span>{channel.label}</span>
                      {configuredChannel && (
                        <span className="ml-auto text-xs text-gray-500">({configuredChannel.name})</span>
                      )}
                    </label>
                  )
                })}
              </div>
            )}
          </div>

          {/* Enable/Disable */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="enabled"
              checked={formData.enabled}
              onChange={(e) => handleChange('enabled', e.target.checked)}
              className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0"
            />
            <label htmlFor="enabled" className="text-sm text-gray-300">
              Enable this rule immediately
            </label>
          </div>
          </div>

          {/* Right Column - Summary */}
          <div className="w-80 p-6 bg-gray-800/30">
            <h3 className="text-sm font-semibold text-white mb-4">Rule Summary</h3>
            <div className="space-y-3">
              {getSummaryText().map((line, idx) => (
                <div key={idx} className="text-sm">
                  <span className="text-gray-400">{line.split(':')[0]}:</span>
                  <span className="text-white ml-1">{line.split(':')[1]}</span>
                </div>
              ))}
            </div>
          </div>
        </form>

        {/* Actions - Below form */}
        <div className="flex items-center justify-end gap-3 border-t border-gray-700 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-gray-800 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-700"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              const form = document.querySelector('form')
              if (form) {
                form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
              }
            }}
            disabled={createRule.isPending || updateRule.isPending}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            {createRule.isPending || updateRule.isPending
              ? 'Saving...'
              : isEditing
                ? 'Update Rule'
                : 'Create Rule'}
          </button>
        </div>
      </div>
    </div>
  )
}
