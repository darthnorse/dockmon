/**
 * Roles Settings Component
 * Admin-only role permissions management interface
 *
 * Phase 5 of Multi-User Support (v2.3.0)
 */

import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  RefreshCw,
  RotateCcw,
  Save,
  Shield,
  User as UserIcon,
  Eye,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Check,
  X,
} from 'lucide-react'
import {
  useCapabilities,
  useRolePermissions,
  useDefaultPermissions,
  useUpdatePermissions,
  useResetPermissions,
} from '@/hooks/useRoles'
import { VALID_ROLES, ROLE_LABELS, type RoleType, type PermissionUpdate } from '@/types/roles'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

const ROLE_ICONS: Record<RoleType, typeof Shield> = {
  admin: Shield,
  user: UserIcon,
  readonly: Eye,
}

const ROLE_COLORS: Record<RoleType, string> = {
  admin: 'text-purple-400',
  user: 'text-blue-400',
  readonly: 'text-gray-400',
}

export function RolesSettings() {
  // Queries
  const { data: capabilitiesData, isLoading: loadingCaps } = useCapabilities()
  const { data: permissionsData, isLoading: loadingPerms, refetch } = useRolePermissions()
  const { data: defaultsData, isLoading: loadingDefaults } = useDefaultPermissions()

  // Mutations
  const updatePermissions = useUpdatePermissions()
  const resetPermissions = useResetPermissions()

  // Local state for edited permissions
  const [editedPermissions, setEditedPermissions] = useState<Record<RoleType, Record<string, boolean>>>({
    admin: {},
    user: {},
    readonly: {},
  })
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())
  const [showResetDialog, setShowResetDialog] = useState(false)
  const [resetRole, setResetRole] = useState<RoleType | null>(null)
  const [showCompareDefaults, setShowCompareDefaults] = useState(false)

  // Initialize edited permissions from server data
  useEffect(() => {
    if (permissionsData?.permissions) {
      setEditedPermissions(permissionsData.permissions as Record<RoleType, Record<string, boolean>>)
    }
  }, [permissionsData])

  // Expand all categories by default
  useEffect(() => {
    if (capabilitiesData?.categories) {
      setExpandedCategories(new Set(capabilitiesData.categories))
    }
  }, [capabilitiesData])

  // Group capabilities by category
  const categorizedCapabilities = useMemo(() => {
    if (!capabilitiesData?.capabilities) return new Map()

    const map = new Map<string, typeof capabilitiesData.capabilities>()
    for (const cap of capabilitiesData.capabilities) {
      const existing = map.get(cap.category) || []
      existing.push(cap)
      map.set(cap.category, existing)
    }
    return map
  }, [capabilitiesData])

  // Check if there are unsaved changes
  const hasChanges = useMemo(() => {
    if (!permissionsData?.permissions) return false

    for (const role of VALID_ROLES) {
      const original = permissionsData.permissions[role] || {}
      const edited = editedPermissions[role] || {}

      for (const cap of Object.keys(edited)) {
        if (original[cap] !== edited[cap]) return true
      }
    }
    return false
  }, [permissionsData, editedPermissions])

  // Count differences from defaults
  const diffFromDefaults = useMemo(() => {
    if (!defaultsData?.permissions) return 0

    let count = 0
    for (const role of VALID_ROLES) {
      const defaults = defaultsData.permissions[role] || {}
      const current = editedPermissions[role] || {}

      for (const [cap, allowed] of Object.entries(defaults)) {
        if (current[cap] !== allowed) count++
      }
    }
    return count
  }, [defaultsData, editedPermissions])

  // Toggle category expansion
  const toggleCategory = useCallback((category: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev)
      if (next.has(category)) {
        next.delete(category)
      } else {
        next.add(category)
      }
      return next
    })
  }, [])

  // Handle permission toggle
  const handleToggle = useCallback((role: RoleType, capability: string) => {
    setEditedPermissions((prev) => ({
      ...prev,
      [role]: {
        ...prev[role],
        [capability]: !prev[role][capability],
      },
    }))
  }, [])

  // Save changes
  const handleSave = async () => {
    if (!permissionsData?.permissions) return

    const changes: PermissionUpdate[] = []

    for (const role of VALID_ROLES) {
      const original = permissionsData.permissions[role] || {}
      const edited = editedPermissions[role] || {}

      for (const [capability, allowed] of Object.entries(edited)) {
        if (original[capability] !== allowed) {
          changes.push({ role, capability, allowed })
        }
      }
    }

    if (changes.length > 0) {
      await updatePermissions.mutateAsync({ permissions: changes })
    }
  }

  // Reset permissions
  const handleResetConfirm = async () => {
    await resetPermissions.mutateAsync(resetRole || undefined)
    setShowResetDialog(false)
    setResetRole(null)
  }

  // Open reset dialog
  const openResetDialog = (role: RoleType | null) => {
    setResetRole(role)
    setShowResetDialog(true)
  }

  // Discard changes
  const handleDiscard = () => {
    if (permissionsData?.permissions) {
      setEditedPermissions(permissionsData.permissions as Record<RoleType, Record<string, boolean>>)
    }
  }

  // Check if permission differs from default
  const isDifferentFromDefault = (role: RoleType, capability: string) => {
    if (!defaultsData?.permissions) return false
    const defaultValue = defaultsData.permissions[role]?.[capability] ?? false
    const currentValue = editedPermissions[role]?.[capability] ?? false
    return currentValue !== defaultValue
  }

  const isLoading = loadingCaps || loadingPerms || loadingDefaults

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <RefreshCw className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white">Role Permissions</h2>
          <p className="mt-1 text-sm text-gray-400">
            Customize what each role can do in the system
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => openResetDialog(null)}
            className="text-orange-400 hover:text-orange-300"
          >
            <RotateCcw className="mr-2 h-4 w-4" />
            Reset All
          </Button>
        </div>
      </div>

      {/* Compare to defaults toggle */}
      <div className="flex items-center justify-between rounded-lg border border-gray-700 bg-gray-800/50 p-3">
        <div className="flex items-center gap-3">
          <label className="relative inline-flex cursor-pointer items-center">
            <input
              type="checkbox"
              checked={showCompareDefaults}
              onChange={(e) => setShowCompareDefaults(e.target.checked)}
              className="peer sr-only"
            />
            <div className="peer h-5 w-9 rounded-full bg-gray-700 after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-gray-400 after:transition-all after:content-[''] peer-checked:bg-blue-600 peer-checked:after:translate-x-full peer-checked:after:bg-white" />
          </label>
          <span className="text-sm text-gray-300">
            Highlight differences from defaults
          </span>
        </div>
        {diffFromDefaults > 0 && (
          <span className="rounded-full bg-orange-900/50 px-2 py-0.5 text-xs text-orange-300">
            {diffFromDefaults} change{diffFromDefaults !== 1 ? 's' : ''} from defaults
          </span>
        )}
      </div>

      {/* Unsaved changes warning */}
      {hasChanges && (
        <div className="flex items-center justify-between rounded-lg border border-yellow-700 bg-yellow-900/20 p-3">
          <div className="flex items-center gap-2 text-yellow-300">
            <AlertTriangle className="h-4 w-4" />
            <span className="text-sm">You have unsaved changes</span>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={handleDiscard}>
              Discard
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={updatePermissions.isPending}
            >
              {updatePermissions.isPending ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              Save Changes
            </Button>
          </div>
        </div>
      )}

      {/* Role headers */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="min-w-[250px] p-3 text-left text-sm font-medium text-gray-400">
                Capability
              </th>
              {VALID_ROLES.map((role) => {
                const Icon = ROLE_ICONS[role]
                return (
                  <th key={role} className="w-28 p-3 text-center">
                    <div className="flex flex-col items-center gap-1">
                      <Icon className={`h-5 w-5 ${ROLE_COLORS[role]}`} />
                      <span className="text-sm font-medium text-gray-300">
                        {ROLE_LABELS[role]}
                      </span>
                      <button
                        onClick={() => openResetDialog(role)}
                        className="mt-1 text-xs text-gray-500 hover:text-gray-300"
                      >
                        Reset
                      </button>
                    </div>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {Array.from(categorizedCapabilities.entries()).map(([category, capabilities]) => (
              <CategorySection
                key={category}
                category={category}
                capabilities={capabilities}
                expanded={expandedCategories.has(category)}
                onToggle={() => toggleCategory(category)}
                editedPermissions={editedPermissions}
                onPermissionToggle={handleToggle}
                showCompareDefaults={showCompareDefaults}
                isDifferentFromDefault={isDifferentFromDefault}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Reset confirmation dialog */}
      <Dialog open={showResetDialog} onOpenChange={setShowResetDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset Permissions</DialogTitle>
            <DialogDescription>
              {resetRole
                ? `Are you sure you want to reset all permissions for the "${ROLE_LABELS[resetRole]}" role to defaults?`
                : 'Are you sure you want to reset ALL role permissions to defaults?'}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowResetDialog(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleResetConfirm}
              disabled={resetPermissions.isPending}
            >
              {resetPermissions.isPending && (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              )}
              Reset
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// Category section component
interface CategorySectionProps {
  category: string
  capabilities: Array<{ name: string; capability: string; description: string }>
  expanded: boolean
  onToggle: () => void
  editedPermissions: Record<RoleType, Record<string, boolean>>
  onPermissionToggle: (role: RoleType, capability: string) => void
  showCompareDefaults: boolean
  isDifferentFromDefault: (role: RoleType, capability: string) => boolean
}

function CategorySection({
  category,
  capabilities,
  expanded,
  onToggle,
  editedPermissions,
  onPermissionToggle,
  showCompareDefaults,
  isDifferentFromDefault,
}: CategorySectionProps) {
  return (
    <>
      {/* Category header row */}
      <tr
        className="cursor-pointer border-b border-gray-800 bg-gray-900/50 hover:bg-gray-800/50"
        onClick={onToggle}
      >
        <td className="p-3" colSpan={4}>
          <div className="flex items-center gap-2">
            {expanded ? (
              <ChevronDown className="h-4 w-4 text-gray-400" />
            ) : (
              <ChevronRight className="h-4 w-4 text-gray-400" />
            )}
            <span className="font-medium text-white">{category}</span>
            <span className="text-xs text-gray-500">({capabilities.length})</span>
          </div>
        </td>
      </tr>

      {/* Capability rows */}
      {expanded &&
        capabilities.map((cap) => (
          <tr key={cap.capability} className="border-b border-gray-800 hover:bg-gray-800/30">
            <td className="p-3">
              <div className="flex flex-col">
                <span className="text-sm font-medium text-gray-200">{cap.name}</span>
                <span className="text-xs text-gray-500">{cap.description}</span>
              </div>
            </td>
            {VALID_ROLES.map((role) => {
              const isAllowed = editedPermissions[role]?.[cap.capability] ?? false
              const isDifferent = showCompareDefaults && isDifferentFromDefault(role, cap.capability)

              return (
                <td key={role} className="p-3 text-center">
                  <button
                    onClick={() => onPermissionToggle(role, cap.capability)}
                    className={`
                      inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors
                      ${
                        isAllowed
                          ? 'bg-green-900/50 text-green-400 hover:bg-green-800/50'
                          : 'bg-gray-800 text-gray-500 hover:bg-gray-700'
                      }
                      ${isDifferent ? 'ring-2 ring-orange-500/50' : ''}
                    `}
                    title={isAllowed ? 'Allowed' : 'Denied'}
                  >
                    {isAllowed ? <Check className="h-4 w-4" /> : <X className="h-4 w-4" />}
                  </button>
                </td>
              )
            })}
          </tr>
        ))}
    </>
  )
}
