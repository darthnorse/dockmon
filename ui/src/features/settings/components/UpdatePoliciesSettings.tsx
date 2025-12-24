/**
 * Update Policies Settings Component
 *
 * Manages global update validation policies:
 * - View all validation patterns grouped by category
 * - Toggle entire categories on/off
 * - Add/remove custom patterns
 * - Expandable pattern lists
 */

import { useState } from 'react'
import { toast } from 'sonner'
import {
  Database,
  Network,
  Activity,
  Shield,
  PlusCircle,
  ChevronDown,
  ChevronRight,
  X,
  Loader2
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useUpdatePolicies,
  useTogglePolicyCategory,
  useCreateCustomPattern,
  useDeleteCustomPattern,
  useUpdatePolicyAction
} from '@/features/containers/hooks/useUpdatePolicies'
import type { UpdatePolicyCategory, UpdatePolicyAction } from '@/features/containers/types/updatePolicy'
import { ACTION_OPTIONS } from '@/features/containers/types/updatePolicy'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

/**
 * Category metadata for display
 */
const CATEGORY_CONFIG: Record<
  Exclude<UpdatePolicyCategory, 'custom'>,
  {
    label: string
    description: string
    icon: React.ComponentType<React.SVGProps<SVGSVGElement>>
    color: string
  }
> = {
  databases: {
    label: 'Databases',
    description: 'Database containers (postgres, mysql, mongodb, etc.)',
    icon: Database,
    color: 'text-blue-400'
  },
  proxies: {
    label: 'Proxies',
    description: 'Reverse proxy and ingress containers (traefik, nginx, caddy)',
    icon: Network,
    color: 'text-purple-400'
  },
  monitoring: {
    label: 'Monitoring',
    description: 'Monitoring and observability containers (grafana, prometheus)',
    icon: Activity,
    color: 'text-green-400'
  },
  critical: {
    label: 'Critical',
    description: 'Critical infrastructure containers (portainer, dockmon)',
    icon: Shield,
    color: 'text-red-400'
  }
}

export function UpdatePoliciesSettings() {
  const { data: policies, isLoading, isError } = useUpdatePolicies()
  const toggleCategory = useTogglePolicyCategory()
  const createPattern = useCreateCustomPattern()
  const deletePattern = useDeleteCustomPattern()
  const updateAction = useUpdatePolicyAction()

  const [expandedCategories, setExpandedCategories] = useState<Set<UpdatePolicyCategory>>(new Set())
  const [customPatternInput, setCustomPatternInput] = useState('')
  const [newPatternAction, setNewPatternAction] = useState<UpdatePolicyAction>('warn')

  /**
   * Toggle category expansion
   */
  const toggleExpanded = (category: UpdatePolicyCategory) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev)
      if (next.has(category)) {
        next.delete(category)
      } else {
        next.add(category)
      }
      return next
    })
  }

  /**
   * Handle category toggle switch
   */
  const handleToggleCategory = async (category: UpdatePolicyCategory, enabled: boolean) => {
    try {
      await toggleCategory.mutateAsync({ category, enabled })
      toast.success(`${CATEGORY_CONFIG[category as keyof typeof CATEGORY_CONFIG]?.label || category} patterns ${enabled ? 'enabled' : 'disabled'}`)
    } catch (error) {
      toast.error('Failed to update category', {
        description: error instanceof Error ? error.message : 'Unknown error'
      })
    }
  }

  /**
   * Handle add custom pattern
   */
  const handleAddCustomPattern = async () => {
    const pattern = customPatternInput.trim()
    if (!pattern) {
      toast.error('Please enter a pattern')
      return
    }

    try {
      await createPattern.mutateAsync({ pattern, action: newPatternAction })
      toast.success(`Custom pattern '${pattern}' added with action '${newPatternAction}'`)
      setCustomPatternInput('')
      setNewPatternAction('warn') // Reset to default
    } catch (error) {
      if (error instanceof Error && error.message.includes('already exists')) {
        toast.error(`Pattern '${pattern}' already exists`)
      } else {
        toast.error('Failed to add custom pattern', {
          description: error instanceof Error ? error.message : 'Unknown error'
        })
      }
    }
  }

  /**
   * Handle update policy action
   */
  const handleUpdateAction = async (policyId: number, pattern: string, action: UpdatePolicyAction) => {
    try {
      await updateAction.mutateAsync({ policyId, action })
      toast.success(`Pattern '${pattern}' action updated to '${action}'`)
    } catch (error) {
      toast.error('Failed to update action', {
        description: error instanceof Error ? error.message : 'Unknown error'
      })
    }
  }

  /**
   * Handle delete custom pattern
   */
  const handleDeleteCustomPattern = async (policyId: number, pattern: string) => {
    try {
      await deletePattern.mutateAsync({ policyId })
      toast.success(`Custom pattern '${pattern}' removed`)
    } catch (error) {
      toast.error('Failed to remove custom pattern', {
        description: error instanceof Error ? error.message : 'Unknown error'
      })
    }
  }

  /**
   * Check if all patterns in category are enabled
   */
  const isCategoryEnabled = (category: UpdatePolicyCategory): boolean => {
    const categoryPolicies = policies?.categories[category] || []
    if (categoryPolicies.length === 0) return false
    return categoryPolicies.every((p) => p.enabled)
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4">
        <p className="text-sm text-destructive">Failed to load update policies. Please try again.</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h3 className="text-lg font-semibold text-text-primary">Update Validation Policies</h3>
        <p className="text-sm text-text-secondary mt-1">
          Configure automatic validation rules for container updates. Matched containers will
          require confirmation before updating.
        </p>
      </div>

      {/* Built-in Categories */}
      <div className="space-y-3">
        {(Object.keys(CATEGORY_CONFIG) as Array<keyof typeof CATEGORY_CONFIG>).map((category) => {
          const config = CATEGORY_CONFIG[category]
          const categoryPolicies = policies?.categories[category] || []
          const isExpanded = expandedCategories.has(category)
          const isEnabled = isCategoryEnabled(category)
          const Icon = config.icon

          return (
            <div key={category} className="bg-surface-2 rounded-lg border border-border overflow-hidden">
              {/* Category Header */}
              <div className="p-4 flex items-center justify-between">
                <div className="flex items-center gap-3 flex-1">
                  <button
                    onClick={() => toggleExpanded(category)}
                    className="text-text-tertiary hover:text-text-primary transition-colors"
                    aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${config.label}`}
                  >
                    {isExpanded ? (
                      <ChevronDown className="w-4 h-4" />
                    ) : (
                      <ChevronRight className="w-4 h-4" />
                    )}
                  </button>

                  <div className={config.color}>
                    <Icon className="w-5 h-5" />
                  </div>

                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-medium text-text-primary">{config.label}</h4>
                      <span className="text-xs text-text-tertiary">
                        ({categoryPolicies.length} patterns)
                      </span>
                    </div>
                    <p className="text-xs text-text-secondary mt-0.5">{config.description}</p>
                  </div>
                </div>

                <Switch
                  checked={isEnabled}
                  onCheckedChange={(checked) => handleToggleCategory(category, checked)}
                  disabled={toggleCategory.isPending || categoryPolicies.length === 0}
                  aria-label={`Toggle ${config.label} category`}
                />
              </div>

              {/* Expanded Pattern List */}
              {isExpanded && categoryPolicies.length > 0 && (
                <div className="px-4 pb-4 border-t border-border bg-surface-3">
                  <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                    {categoryPolicies.map((policy) => (
                      <div
                        key={policy.id}
                        className={`text-xs px-2 py-1 rounded font-mono ${
                          policy.enabled
                            ? 'bg-surface-1 text-text-primary border border-border'
                            : 'bg-surface-2 text-text-tertiary border border-border/50'
                        }`}
                      >
                        {policy.pattern}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Custom Patterns Section */}
      <div className="bg-surface-2 rounded-lg border border-border p-4">
        <div className="flex items-start gap-3 mb-4">
          <div className="text-gray-400">
            <PlusCircle className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <h4 className="text-sm font-medium text-text-primary">Custom Patterns</h4>
            <p className="text-xs text-text-secondary mt-0.5">
              Add your own patterns to match against container and image names
            </p>
          </div>
        </div>

        {/* Add Custom Pattern Input */}
        <div className="flex gap-2 mb-4">
          <div className="flex-1">
            <Label htmlFor="custom-pattern" className="sr-only">
              Custom pattern
            </Label>
            <Input
              id="custom-pattern"
              placeholder="Enter pattern (e.g., myapp)"
              value={customPatternInput}
              onChange={(e) => setCustomPatternInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  handleAddCustomPattern()
                }
              }}
              disabled={createPattern.isPending}
              className="h-9"
            />
          </div>
          <Select
            value={newPatternAction}
            onValueChange={(value) => setNewPatternAction(value as UpdatePolicyAction)}
            disabled={createPattern.isPending}
          >
            <SelectTrigger className="w-[100px] h-9">
              <SelectValue>
                {ACTION_OPTIONS.find((o) => o.value === newPatternAction)?.label}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {ACTION_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            onClick={handleAddCustomPattern}
            disabled={createPattern.isPending || !customPatternInput.trim()}
            size="sm"
            className="h-9"
          >
            {createPattern.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              'Add'
            )}
          </Button>
        </div>

        {/* Custom Patterns List */}
        {policies?.categories.custom && policies.categories.custom.length > 0 ? (
          <div className="space-y-2">
            {policies.categories.custom.map((policy) => (
              <div
                key={policy.id}
                className="flex items-center justify-between bg-surface-3 rounded px-3 py-2 border border-border gap-2"
              >
                <span className="text-sm font-mono text-text-primary flex-1">{policy.pattern}</span>
                <Select
                  value={policy.action}
                  onValueChange={(value) => handleUpdateAction(policy.id, policy.pattern, value as UpdatePolicyAction)}
                  disabled={updateAction.isPending}
                >
                  <SelectTrigger className="w-[100px] h-8">
                    <SelectValue>
                      {ACTION_OPTIONS.find((o) => o.value === policy.action)?.label}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {ACTION_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <button
                  onClick={() => handleDeleteCustomPattern(policy.id, policy.pattern)}
                  disabled={deletePattern.isPending}
                  className="text-text-tertiary hover:text-destructive transition-colors disabled:opacity-50"
                  aria-label={`Delete pattern ${policy.pattern}`}
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-text-tertiary italic">No custom patterns added yet</p>
        )}
      </div>

      {/* Help Text */}
      <div className="bg-info/10 border border-info/20 rounded-lg p-4">
        <p className="text-xs text-info/90">
          <strong>How it works:</strong> Patterns match against container and image names.
          <br /><br />
          <strong>Warn:</strong> Matched containers will require user confirmation before auto-updating.
          <br />
          <strong>Ignore:</strong> Matched containers are excluded from automatic update checks entirely.
          You can still manually check for updates via the container's Updates tab.
        </p>
      </div>
    </div>
  )
}
