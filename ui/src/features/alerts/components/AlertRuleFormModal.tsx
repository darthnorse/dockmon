/**
 * AlertRuleFormModal Component
 *
 * Form for creating and editing alert rules
 */

import { useState, useRef, useEffect } from 'react'
import { X, Search, Check, Bell, BellRing, Send, MessageSquare, Hash, Smartphone, Mail, Globe } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useCreateAlertRule, useUpdateAlertRule } from '../hooks/useAlertRules'
import { useNotificationChannels } from '../hooks/useNotificationChannels'
import type { AlertRule, AlertSeverity, AlertScope, AlertRuleRequest } from '@/types/alerts'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import type { Host } from '@/types/api'
import type { Container } from '@/features/containers/types'
import { apiClient } from '@/lib/api/client'
import { NoChannelsConfirmModal } from './NoChannelsConfirmModal'

interface Props {
  rule?: AlertRule | null
  onClose: () => void
}

/**
 * Form data for alert rule creation/editing
 */
interface AlertRuleFormData {
  name: string
  description: string
  scope: AlertScope
  kind: string
  enabled: boolean
  severity: AlertSeverity
  metric?: string | undefined
  threshold?: number | undefined
  operator?: string | undefined
  duration_seconds: number
  occurrences: number
  clear_threshold?: number | null | undefined
  clear_duration_seconds?: number | null | undefined
  cooldown_seconds: number
  host_selector_all: boolean
  host_selector_ids: string[]
  container_selector_all: boolean
  container_selector_included: string[]
  container_run_mode: 'all' | 'should_run' | 'on_demand'
  notify_channels: string[]
  custom_template: string | null
  auto_resolve_updates: boolean
  suppress_during_updates: boolean
}

/**
 * Container selector structure for API requests
 */
interface ContainerSelector {
  tags?: string[]
  include_all?: boolean
  include?: string[]
  exclude?: string[]
  should_run?: boolean | null
}

const RULE_KINDS = [
  {
    value: 'cpu_high',
    label: 'High CPU Usage',
    description: 'Alert when CPU usage exceeds threshold',
    category: 'Performance',
    requiresMetric: true,
    metric: 'cpu_percent',
    defaultOperator: '>=',
    defaultThreshold: 90,
    scopes: ['host', 'container']
  },
  {
    value: 'memory_high',
    label: 'High Memory Usage',
    description: 'Alert when memory usage exceeds threshold',
    category: 'Performance',
    requiresMetric: true,
    metric: 'memory_percent',
    defaultOperator: '>=',
    defaultThreshold: 90,
    scopes: ['host', 'container']
  },
  {
    value: 'disk_low',
    label: 'Low Disk Space',
    description: 'Alert when disk usage exceeds threshold',
    category: 'Performance',
    requiresMetric: true,
    metric: 'disk_percent',
    defaultOperator: '>=',
    defaultThreshold: 85,
    scopes: ['host']
  },
  {
    value: 'container_unhealthy',
    label: 'Container Health Check Failing',
    description: 'Alert when Docker native health check fails (HEALTHCHECK in Dockerfile)',
    category: 'Container State',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'health_check_failed',
    label: 'Health Check Failed',
    description: 'Alert when HTTP/HTTPS health check fails (configured in Health Check tab)',
    category: 'Container State',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'container_stopped',
    label: 'Container Stopped/Died',
    description: 'Alert when container stops or crashes (any exit code). Use clear duration to avoid false positives during restarts.',
    category: 'Container State',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'container_restart',
    label: 'Container Restarted',
    description: 'Alert when container restarts (any restart, expected or unexpected)',
    category: 'Container State',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'host_down',
    label: 'Host Offline',
    description: 'Alert when host becomes unreachable',
    category: 'Host State',
    requiresMetric: false,
    scopes: ['host']
  },
  {
    value: 'update_available',
    label: 'Update Available',
    description: 'Alert when a container image update is available',
    category: 'Updates',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'update_completed',
    label: 'Update Completed',
    description: 'Alert when a container update completes successfully',
    category: 'Updates',
    requiresMetric: false,
    scopes: ['container']
  },
  {
    value: 'update_failed',
    label: 'Update Failed',
    description: 'Alert when a container update fails or rollback occurs',
    category: 'Updates',
    requiresMetric: false,
    scopes: ['container']
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
  { value: 'ntfy', label: 'ntfy', icon: BellRing },
  { value: 'smtp', label: 'Email (SMTP)', icon: Mail },
  { value: 'webhook', label: 'Webhook', icon: Globe },
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
  const { data: channelsData } = useNotificationChannels()

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

  const [formData, setFormData] = useState<AlertRuleFormData>(() => {
    // Determine if this rule requires a metric
    const ruleKind = rule?.kind || 'cpu_high'
    const kindConfig = RULE_KINDS.find((k) => k.value === ruleKind)
    const isMetricDriven = kindConfig?.requiresMetric ?? true

    // Parse container selector to extract should_run filter and include list
    const parseContainerSelector = (json: string | null | undefined) => {
      if (!json) return { all: true, included: [], should_run: null }
      try {
        const parsed = JSON.parse(json)
        if (parsed.include_all) {
          return {
            all: true,
            included: [],
            should_run: parsed.should_run || null
          }
        }
        if (parsed.include) {
          // Explicit include list for manual selection
          return {
            all: false,
            included: parsed.include,
            should_run: parsed.should_run || null
          }
        }
        return { all: true, included: [], should_run: null }
      } catch {
        return { all: true, included: [], should_run: null }
      }
    }

    const containerSelector = parseContainerSelector(rule?.container_selector_json)

    const scope = rule?.scope || 'container'

    return {
      name: rule?.name || '',
      description: rule?.description || '',
      scope: scope,
      kind: ruleKind,
      enabled: rule?.enabled ?? true,
      severity: rule?.severity || 'warning',
      metric: rule?.metric || 'cpu_percent',
      threshold: rule?.threshold || 90,
      operator: rule?.operator || '>=',
      // Event-driven rules: fire immediately (0s, 1 occurrence), auto-resolve after 30s, cooldown 15s
      // Metric-driven rules: require sustained breach (300s, 3 occurrences), auto-resolve after 60s, cooldown 5 min
      duration_seconds: rule?.duration_seconds ?? (isMetricDriven ? 300 : 0),
      occurrences: rule?.occurrences ?? (isMetricDriven ? 3 : 1),
      clear_threshold: rule?.clear_threshold,
      clear_duration_seconds: rule?.clear_duration_seconds ?? (isMetricDriven ? 60 : 30),
      cooldown_seconds: rule?.cooldown_seconds ?? (isMetricDriven ? 300 : 15),
      // Selectors
      host_selector_all: parseSelector(rule?.host_selector_json).all,
      host_selector_ids: parseSelector(rule?.host_selector_json).selected,
      container_selector_all: containerSelector.all,
      container_selector_included: containerSelector.included,
      container_run_mode: containerSelector.should_run === null ? 'all' : containerSelector.should_run ? 'should_run' : 'on_demand',
      notify_channels: rule?.notify_channels_json ? JSON.parse(rule.notify_channels_json) : [],
      custom_template: rule?.custom_template !== undefined ? rule.custom_template : null,
      // Auto-resolve defaults to false - user can enable for any alert type
      auto_resolve_updates: rule?.auto_resolve ?? false,
      // Default suppress_during_updates to true for container-scoped rules
      suppress_during_updates: rule?.suppress_during_updates ?? (scope === 'container'),
    }
  })

  const [error, setError] = useState<string | null>(null)
  const [showNoChannelsConfirm, setShowNoChannelsConfirm] = useState(false)

  // Host/Container dropdown state
  const [hostSearchInput, setHostSearchInput] = useState('')
  const [showHostDropdown, setShowHostDropdown] = useState(false)
  const hostDropdownRef = useRef<HTMLDivElement>(null)
  const [containerSearchInput, setContainerSearchInput] = useState('')
  const [showContainerDropdown, setShowContainerDropdown] = useState(false)
  const containerDropdownRef = useRef<HTMLDivElement>(null)

  // Tag selector state (always available, not scope-dependent)
  const [tagSearchInput, setTagSearchInput] = useState('')
  const [availableTags, setAvailableTags] = useState<string[]>([])
  const [selectedTags, setSelectedTags] = useState<string[]>(() => {
    // Initialize with existing tags if editing - check selectors not labels_json
    if (rule) {
      try {
        // Check host_selector for tags
        if (rule.host_selector_json) {
          const parsed = JSON.parse(rule.host_selector_json)
          if (parsed.tags && Array.isArray(parsed.tags)) return parsed.tags
        }
        // Check container_selector for tags
        if (rule.container_selector_json) {
          const parsed = JSON.parse(rule.container_selector_json)
          if (parsed.tags && Array.isArray(parsed.tags)) return parsed.tags
        }
      } catch {
        // Parsing failed, fall through
      }
    }
    return []
  })

  // Fetch available tags based on scope (host or container)
  useEffect(() => {
    const fetchTags = async () => {
      try {
        // Use different endpoints based on scope to get only relevant tags
        const endpoint = formData.scope === 'host'
          ? `/api/hosts/tags/suggest?q=${tagSearchInput}&limit=50`
          : `/api/tags/suggest?q=${tagSearchInput}&limit=50`
        const res = await fetch(endpoint)
        const data = await res.json()
        // Tags API returns objects like {id, name, color, kind}, extract just the names
        const tagNames = Array.isArray(data.tags)
          ? data.tags.map((t: string | { name: string }) => typeof t === 'string' ? t : t.name)
          : []
        setAvailableTags(tagNames)
      } catch (err) {
        console.error('Failed to fetch tags:', err)
      }
    }

    fetchTags()
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

  const filteredContainers = containers
    .filter((c) => {
      // Apply run mode filter
      if (formData.container_run_mode === 'should_run' && c.desired_state !== 'should_run') return false
      if (formData.container_run_mode === 'on_demand' && c.desired_state !== 'on_demand') return false

      // Apply search filter
      return (
        c.name.toLowerCase().includes(containerSearchInput.toLowerCase()) ||
        (c.host_name && c.host_name.toLowerCase().includes(containerSearchInput.toLowerCase()))
      )
    })

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

    // Check if user has selected notification channels
    if (formData.notify_channels.length === 0) {
      // Show confirmation modal
      setShowNoChannelsConfirm(true)
      return
    }

    // Proceed with submission
    await performSubmit()
  }

  const performSubmit = async () => {
    try {
      // Prepare request data
      const requestData: Partial<AlertRuleRequest> = {
        name: formData.name,
        description: formData.description,
        scope: formData.scope,
        kind: formData.kind,
        enabled: formData.enabled,
        severity: formData.severity,
        cooldown_seconds: formData.cooldown_seconds,
      }

      // Add metric fields only if required
      if (requiresMetric) {
        if (formData.metric !== undefined) {
          requestData.metric = formData.metric
        }
        if (formData.threshold !== undefined) {
          requestData.threshold = formData.threshold
        }
        if (formData.operator !== undefined) {
          requestData.operator = formData.operator
        }
        if (formData.clear_threshold !== undefined && formData.clear_threshold !== null) {
          requestData.clear_threshold = formData.clear_threshold
        }
        if (formData.clear_duration_seconds !== undefined && formData.clear_duration_seconds !== null) {
          requestData.clear_duration_seconds = formData.clear_duration_seconds
        }
      } else {
        // For non-metric (event-driven) rules, add clear_duration_seconds
        if (formData.clear_duration_seconds !== undefined && formData.clear_duration_seconds !== null) {
          requestData.clear_duration_seconds = formData.clear_duration_seconds
        }
      }

      // Duration and occurrences apply to ALL rule types (for rate-limiting)
      requestData.duration_seconds = formData.duration_seconds
      requestData.occurrences = formData.occurrences

      // Add selectors - Tag-based OR individual selection (mutually exclusive)
      if (formData.scope === 'host') {
        // Host scope selectors
        if (selectedTags.length > 0) {
          // Tag-based: hosts with ANY of these tags
          requestData.host_selector_json = JSON.stringify({ tags: selectedTags })
        } else if (formData.host_selector_all) {
          requestData.host_selector_json = JSON.stringify({ include_all: true })
        } else if (formData.host_selector_ids.length > 0) {
          requestData.host_selector_json = JSON.stringify({ include: formData.host_selector_ids })
        }
      } else if (formData.scope === 'container') {
        // Container scope selectors
        if (selectedTags.length > 0) {
          // Tag-based: containers with ANY of these tags
          const containerSelector: ContainerSelector = { tags: selectedTags }
          // Add should_run filter if specified
          if (formData.container_run_mode === 'should_run') {
            containerSelector.should_run = true
          } else if (formData.container_run_mode === 'on_demand') {
            containerSelector.should_run = false
          }
          requestData.container_selector_json = JSON.stringify(containerSelector)
        } else if (formData.container_selector_all) {
          const containerSelector: ContainerSelector = { include_all: true }
          // Add should_run filter if specified
          if (formData.container_run_mode === 'should_run') {
            containerSelector.should_run = true
          } else if (formData.container_run_mode === 'on_demand') {
            containerSelector.should_run = false
          }
          requestData.container_selector_json = JSON.stringify(containerSelector)
        } else if (formData.container_selector_included.length > 0) {
          const containerSelector: ContainerSelector = { include: formData.container_selector_included }
          // Add should_run filter if specified
          if (formData.container_run_mode === 'should_run') {
            containerSelector.should_run = true
          } else if (formData.container_run_mode === 'on_demand') {
            containerSelector.should_run = false
          }
          requestData.container_selector_json = JSON.stringify(containerSelector)
        }
      }

      // Add notification channels
      if (formData.notify_channels.length > 0) {
        requestData.notify_channels_json = JSON.stringify(formData.notify_channels)
      }

      // Add custom template (null/empty string means use category default)
      if (formData.custom_template !== undefined && formData.custom_template !== null) {
        requestData.custom_template = formData.custom_template
      }

      // Add auto_resolve flag for all alert types
      requestData.auto_resolve = formData.auto_resolve_updates || false

      // Add suppress_during_updates flag for container-scoped rules
      if (formData.scope === 'container') {
        requestData.suppress_during_updates = formData.suppress_during_updates || false
      }

      if (isEditing && rule) {
        await updateRule.mutateAsync({ ruleId: rule.id, rule: requestData as AlertRuleRequest })
      } else {
        await createRule.mutateAsync(requestData as AlertRuleRequest)
      }
      onClose()
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save rule'
      setError(errorMessage)
    }
  }

  const handleChange = <K extends keyof AlertRuleFormData>(field: K, value: AlertRuleFormData[K]) => {
    setFormData((prev) => {
      const updated = { ...prev, [field]: value }

      // When scope changes, reset rule kind if current selection is invalid for new scope
      // Also clear selected tags since they're scope-specific
      if (field === 'scope') {
        const newScope = value as AlertScope
        setSelectedTags([])
        // Default suppress_during_updates to true for container scope
        updated.suppress_during_updates = (newScope === 'container')

        const currentKind = RULE_KINDS.find((k) => k.value === prev.kind)
        if (currentKind && !currentKind.scopes.includes(newScope)) {
          // Find first valid rule kind for new scope
          const firstValidKind = RULE_KINDS.find((k) => k.scopes.includes(newScope))
          if (firstValidKind) {
            updated.kind = firstValidKind.value
            if (firstValidKind.requiresMetric) {
              // Metric-driven rule defaults
              updated.metric = firstValidKind.metric
              updated.operator = firstValidKind.defaultOperator
              updated.threshold = firstValidKind.defaultThreshold
              updated.duration_seconds = 300
              updated.occurrences = 3
              updated.cooldown_seconds = 300
              updated.clear_duration_seconds = undefined
            } else {
              // Event-driven rule defaults
              updated.duration_seconds = 0
              updated.occurrences = 1
              updated.cooldown_seconds = 15
              updated.clear_duration_seconds = 30
            }
          }
        }
      }

      // Auto-set metric, operator, threshold, and timing when rule kind changes
      if (field === 'kind') {
        const kind = RULE_KINDS.find((k) => k.value === value)
        if (kind?.requiresMetric) {
          // Metric-driven rule defaults
          updated.metric = kind.metric
          updated.operator = kind.defaultOperator
          updated.threshold = kind.defaultThreshold
          updated.duration_seconds = 300
          updated.occurrences = 3
          updated.cooldown_seconds = 300
          updated.clear_duration_seconds = undefined
        } else {
          // Event-driven rule defaults
          updated.duration_seconds = 0
          updated.occurrences = 1
          updated.cooldown_seconds = 15
          updated.clear_duration_seconds = 30
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
      if (selectedTags.length > 0) {
        parts.push(`Scope: All hosts with tags [${selectedTags.join(', ')}]`)
      } else if (formData.host_selector_all) {
        parts.push('Scope: All hosts')
      } else if (formData.host_selector_ids.length > 0) {
        parts.push(`Scope: ${formData.host_selector_ids.length} selected host${formData.host_selector_ids.length > 1 ? 's' : ''}`)
      }
    } else if (formData.scope === 'container') {
      let scopeText = ''
      if (selectedTags.length > 0) {
        scopeText = `All containers with tags [${selectedTags.join(', ')}]`
      } else if (formData.container_selector_all) {
        scopeText = 'All containers'
      } else if (formData.container_selector_included.length > 0) {
        scopeText = `${formData.container_selector_included.length} selected container${formData.container_selector_included.length > 1 ? 's' : ''}`
      }
      // Add run mode filter
      if (formData.container_run_mode === 'should_run') {
        scopeText += ' (Should Run only)'
      } else if (formData.container_run_mode === 'on_demand') {
        scopeText += ' (On-Demand only)'
      }
      if (scopeText) {
        parts.push(`Scope: ${scopeText}`)
      }
    } else {
      parts.push(`Scope: ${formData.scope}`)
    }

    // Severity
    parts.push(`Severity: ${formData.severity}`)

    // Timing Configuration
    if (!requiresMetric) {
      // For event-driven rules, show duration/occurrences if non-default
      if (formData.duration_seconds > 0 || formData.occurrences > 1) {
        parts.push(`Duration: ${formData.duration_seconds}s (${formData.occurrences} occurrence${formData.occurrences > 1 ? 's' : ''})`)
      }
      // Show clear duration for event-driven rules
      if (formData.clear_duration_seconds !== undefined && formData.clear_duration_seconds !== null && formData.clear_duration_seconds > 0) {
        parts.push(`Clear Duration: ${formData.clear_duration_seconds}s`)
      }
    } else {
      // For metric-driven rules, show clear threshold/duration if set
      if (formData.clear_threshold !== undefined && formData.clear_threshold !== null) {
        parts.push(`Clear Threshold: ${formData.clear_threshold}%`)
      }
      if (formData.clear_duration_seconds !== undefined && formData.clear_duration_seconds !== null && formData.clear_duration_seconds > 0) {
        parts.push(`Clear Duration: ${formData.clear_duration_seconds}s`)
      }
    }

    // Cooldown
    parts.push(`Cooldown: ${formData.cooldown_seconds}s`)

    // Suppress during updates (container scope only)
    if (formData.scope === 'container') {
      parts.push(`Suppress during updates: ${formData.suppress_during_updates ? 'Yes' : 'No'}`)
    }

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
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/70 z-50"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal */}
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="w-full max-w-6xl rounded-lg border border-gray-700 bg-[#0d1117] shadow-2xl max-h-[90vh] overflow-y-auto pointer-events-auto">
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
          </div>

          {/* Scope Selection */}
          <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
            <h3 className="text-sm font-semibold text-white">Alert Scope</h3>
            <p className="text-xs text-gray-400">
              Choose whether this rule applies to hosts or containers
            </p>
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
              </select>
            </div>
          </div>

          {/* Rule Configuration */}
          <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
            <h3 className="text-sm font-semibold text-white">Rule Configuration</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">Rule Type *</label>
                <select
                  value={formData.kind}
                  onChange={(e) => handleChange('kind', e.target.value)}
                  required
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                >
                  {/* Group rule kinds by category */}
                  {Object.entries(
                    availableRuleKinds.reduce((groups: Record<string, typeof availableRuleKinds>, kind) => {
                      const category = kind.category || 'Other'
                      if (!groups[category]) groups[category] = []
                      groups[category].push(kind)
                      return groups
                    }, {})
                  ).map(([category, kinds]) => (
                    <optgroup key={category} label={category}>
                      {kinds.map((kind) => (
                        <option key={kind.value} value={kind.value}>
                          {kind.label}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                {selectedKind?.description && (
                  <p className="mt-1 text-xs text-gray-400">{selectedKind.description}</p>
                )}
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
            </div>
          </div>

          {/* Tag Filter (Optional) - Always available */}
          <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
            <h3 className="text-sm font-semibold text-white">Tag-Based Filter (Optional)</h3>
            <p className="text-xs text-gray-400">
              Select tags to apply this rule to all {formData.scope === 'host' ? 'hosts' : 'containers'} with ANY of these tags.
              When tags are selected, individual selection below is disabled.
            </p>

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
                  <p className="mt-1 text-xs text-gray-400">Metric value that triggers auto-resolve (e.g., CPU drops below 80%). Defaults to alert threshold if not specified.</p>
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
                  <p className="mt-1 text-xs text-gray-400">
                    How long the metric must stay below the clear threshold before auto-resolving the alert.
                    Set to 0 for immediate clearing. Defaults to 60s if not specified.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Host Selector */}
          {formData.scope === 'host' && (
            <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">Host Selection</h3>
                {selectedTags.length === 0 && (
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
                )}
              </div>

              {selectedTags.length > 0 ? (
                <div className="rounded-md bg-gray-900/50 border border-gray-700 p-4 text-center">
                  <p className="text-sm text-gray-400">
                    Individual host selection is disabled. This rule applies to all hosts with the selected tags above.
                    Remove tags to manually select hosts.
                  </p>
                </div>
              ) : (
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
              )}
            </div>
          )}

          {/* Container Selector (for container scope) */}
          {formData.scope === 'container' && (
            <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-white">Container Selection</h3>
                {selectedTags.length === 0 && (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        handleChange('container_selector_included', [])
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
                        // Deselect all: switch to manual include mode with empty list
                        handleChange('container_selector_included', [])
                        handleChange('container_selector_all', false)
                      }}
                      className="text-xs text-blue-400 hover:text-blue-300 underline"
                    >
                      Deselect All
                    </button>
                  </div>
                )}
              </div>

              {selectedTags.length > 0 ? (
                <div className="rounded-md bg-gray-900/50 border border-gray-700 p-4 text-center">
                  <p className="text-sm text-gray-400">
                    Individual container selection is disabled. This rule applies to all containers with the selected tags above.
                    Remove tags to manually select containers.
                  </p>
                </div>
              ) : (
                <>
                  {/* Container Run Mode Selector */}
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-2">Container Run Mode</label>
                    <div className="grid grid-cols-3 gap-2">
                      <button
                        type="button"
                        onClick={() => handleChange('container_run_mode', 'all')}
                        className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                          formData.container_run_mode === 'all'
                            ? 'bg-blue-600 text-white'
                            : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                        }`}
                      >
                        All Containers
                      </button>
                      <button
                        type="button"
                        onClick={() => handleChange('container_run_mode', 'should_run')}
                        className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                          formData.container_run_mode === 'should_run'
                            ? 'bg-blue-600 text-white'
                            : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                        }`}
                      >
                        Should Run Only
                      </button>
                      <button
                        type="button"
                        onClick={() => handleChange('container_run_mode', 'on_demand')}
                        className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                          formData.container_run_mode === 'on_demand'
                            ? 'bg-blue-600 text-white'
                            : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
                        }`}
                      >
                        On-Demand Only
                      </button>
                    </div>
                    <p className="mt-2 text-xs text-gray-400">
                      Filter containers by run mode to create separate rules for different severity levels
                    </p>
                  </div>

                  {/* Show container selector only when "All Containers" is selected */}
                  {formData.container_run_mode === 'all' ? (
                    <div ref={containerDropdownRef} className="relative">
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    Select Containers
                    {formData.container_selector_all && filteredContainers.length > 0 && (
                      <span className="ml-2 text-xs text-blue-400">({filteredContainers.length} containers - all selected)</span>
                    )}
                    {!formData.container_selector_all && formData.container_selector_included.length > 0 && (
                      <span className="ml-2 text-xs text-blue-400">({formData.container_selector_included.length} selected)</span>
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
                        const isSelected = formData.container_selector_all || formData.container_selector_included.includes(container.name)
                        return (
                          <button
                            key={container.id}
                            type="button"
                            onClick={() => {
                              if (formData.container_selector_all) {
                                // When "all" is selected, clicking switches to include mode with all except this one
                                const allExcept = filteredContainers.filter(c => c.name !== container.name).map(c => c.name)
                                handleChange('container_selector_included', allExcept)
                                handleChange('container_selector_all', false)
                              } else {
                                // Manual include mode - toggle this container
                                const newNames = isSelected
                                  ? formData.container_selector_included.filter((n: string) => n !== container.name)
                                  : [...formData.container_selector_included, container.name]
                                handleChange('container_selector_included', newNames)
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
            ) : (
              /* Show read-only info when a specific run mode is selected */
              <div className="space-y-2">
                <div className="text-sm text-gray-300">
                  <span className="font-medium">Matching Containers:</span>
                  <span className="ml-2 text-xs text-blue-400">{filteredContainers.length} container{filteredContainers.length !== 1 ? 's' : ''}</span>
                </div>
                <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3">
                  <p className="text-xs text-blue-300">
                    All containers with run mode "{formData.container_run_mode === 'should_run' ? 'Should Run' : 'On-Demand'}" will be monitored automatically.
                    To exclude specific containers from this rule, change their run mode in the container settings.
                  </p>
                </div>
              </div>
            )}
                </>
              )}
            </div>
          )}

          {/* Timing Configuration - Hide for update rules */}
          {!['update_available', 'update_completed', 'update_failed'].includes(formData.kind) && (
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
              {!requiresMetric && (
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-1">Clear Duration (seconds)</label>
                  <input
                    type="number"
                    value={formData.clear_duration_seconds || ''}
                    onChange={(e) => handleChange('clear_duration_seconds', e.target.value ? parseInt(e.target.value) : undefined)}
                    min={0}
                    placeholder="30"
                    className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                  <p className="mt-1 text-xs text-gray-400">
                    Time window for transient issues. If the condition clears within this period, the alert will auto-resolve
                    without sending notifications. Useful for brief outages like container restarts. Default: 30 seconds.
                  </p>
                </div>
              )}

              <div className={!requiresMetric ? '' : 'col-span-2'}>
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
          )}

          {/* Auto-Resolve Option - Available for all alert types */}
          <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
            <h3 className="text-sm font-semibold text-white">Auto-Resolve Behavior</h3>
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                id="auto_resolve_updates"
                checked={formData.auto_resolve_updates || false}
                onChange={(e) => handleChange('auto_resolve_updates', e.target.checked)}
                className="mt-1 h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900"
              />
              <div className="flex-1">
                <label htmlFor="auto_resolve_updates" className="block text-sm font-medium text-gray-300 cursor-pointer">
                  Automatically resolve alert after notification
                </label>
                <p className="mt-1 text-xs text-gray-400">
                  Alert will be auto-resolved immediately after sending notification. Use this if you only want to be notified without keeping alerts in the DockMon alert list.
                </p>
              </div>
            </div>
          </div>

          {/* Suppress During Updates - Only for container-scoped rules */}
          {formData.scope === 'container' && !['update_available', 'update_completed', 'update_failed'].includes(formData.kind) && (
          <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
            <h3 className="text-sm font-semibold text-white">Update Suppression</h3>
            <div className="flex items-start gap-3">
              <input
                type="checkbox"
                id="suppress_during_updates"
                checked={formData.suppress_during_updates || false}
                onChange={(e) => handleChange('suppress_during_updates', e.target.checked)}
                className="mt-1 h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900"
              />
              <div className="flex-1">
                <label htmlFor="suppress_during_updates" className="block text-sm font-medium text-gray-300 cursor-pointer">
                  Suppress alert during container updates
                </label>
                <p className="mt-1 text-xs text-gray-400">
                  Don't trigger this alert while a container is being updated. The alert will be re-evaluated after the update completes - only firing if the issue persists (e.g., container still stopped after update).
                </p>
              </div>
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
                  // Check if there are multiple channels of this type
                  const channelsOfType = configuredChannels.filter(cc => cc.type === channel.value)
                  const showChannelName = channelsOfType.length > 1 && configuredChannel

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
                      <span className="flex items-center gap-1">
                        {channel.label}
                        {showChannelName && (
                          <span className="text-xs text-gray-500">({configuredChannel.name})</span>
                        )}
                      </span>
                    </label>
                  )
                })}
              </div>
            )}
          </div>

          {/* Custom Template (Optional) */}
          <div className="space-y-4 rounded-lg border border-gray-700 bg-gray-800/30 p-4">
            <div>
              <h3 className="text-sm font-semibold text-white">Custom Message Template (Optional)</h3>
              <p className="text-xs text-gray-400">Override the default template for this specific rule</p>
            </div>

            <div>
              <label className="flex items-center gap-2 text-sm text-gray-300 mb-2">
                <input
                  type="checkbox"
                  checked={!!formData.custom_template}
                  onChange={(e) => {
                    if (e.target.checked) {
                      handleChange('custom_template', '')
                    } else {
                      handleChange('custom_template', null)
                    }
                  }}
                  className="h-4 w-4 rounded border-gray-600 bg-gray-800 text-blue-600 focus:ring-2 focus:ring-blue-500 focus:ring-offset-0"
                />
                Use custom template for this rule
              </label>

              {formData.custom_template !== null && formData.custom_template !== undefined && (
                <textarea
                  value={formData.custom_template}
                  onChange={(e) => handleChange('custom_template', e.target.value)}
                  rows={6}
                  placeholder="Enter custom template or leave empty to use category default..."
                  className="w-full rounded-md border border-gray-700 bg-gray-800 px-3 py-2 text-white font-mono text-sm placeholder-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              )}
              {formData.custom_template !== null && formData.custom_template !== undefined && (
                <p className="mt-2 text-xs text-gray-400">
                  Leave empty to use the category-specific template from Settings. Use variables like {'{CONTAINER_NAME}'}.
                </p>
              )}
            </div>
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

      {/* No Channels Confirmation Modal */}
      <NoChannelsConfirmModal
        isOpen={showNoChannelsConfirm}
        onClose={() => setShowNoChannelsConfirm(false)}
        onConfirm={() => {
          setShowNoChannelsConfirm(false)
          void performSubmit()
        }}
        hasConfiguredChannels={configuredChannels.length > 0}
      />
    </>
  )
}
