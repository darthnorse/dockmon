/**
 * Group Permissions Settings Component
 * Admin-only group permissions management interface
 *
 * Group-Based Permissions Refactor (v2.4.0)
 */

import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  RefreshCw,
  Save,
  Users,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Check,
  X,
  Lock,
  Copy,
} from 'lucide-react'
import { useCapabilities } from '@/hooks/useRoles'
import { useGroups, useAllGroupPermissions, useUpdateGroupPermissions, useCopyGroupPermissions } from '@/hooks/useGroups'
import type { Group } from '@/types/groups'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export function GroupPermissionsSettings() {
  // Queries
  const { data: capabilitiesData, isLoading: loadingCaps } = useCapabilities()
  const { data: groupsData, isLoading: loadingGroups } = useGroups()
  const { data: permissionsData, isLoading: loadingPerms, refetch } = useAllGroupPermissions()

  // Mutations
  const updatePermissions = useUpdateGroupPermissions()
  const copyPermissions = useCopyGroupPermissions()

  // Local state for edited permissions
  const [editedPermissions, setEditedPermissions] = useState<Record<number, Record<string, boolean>>>({})
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())
  const [showCopyDialog, setShowCopyDialog] = useState(false)
  const [copyTargetGroupId, setCopyTargetGroupId] = useState<number | null>(null)
  const [copySourceGroupId, setCopySourceGroupId] = useState<string>('')

  const groups = groupsData?.groups || []

  // Initialize edited permissions from server data
  useEffect(() => {
    if (permissionsData?.permissions) {
      setEditedPermissions(permissionsData.permissions)
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

    for (const [groupId, caps] of Object.entries(editedPermissions)) {
      const original = permissionsData.permissions[parseInt(groupId, 10)] || {}
      for (const [cap, allowed] of Object.entries(caps)) {
        if (original[cap] !== allowed) return true
      }
    }
    return false
  }, [permissionsData, editedPermissions])

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
  const handleToggle = useCallback((groupId: number, capability: string) => {
    setEditedPermissions((prev) => ({
      ...prev,
      [groupId]: {
        ...prev[groupId],
        [capability]: !prev[groupId]?.[capability],
      },
    }))
  }, [])

  // Save changes for a specific group
  const handleSaveGroup = async (groupId: number) => {
    if (!permissionsData?.permissions) return

    const original = permissionsData.permissions[groupId] || {}
    const edited = editedPermissions[groupId] || {}
    const changes: Array<{ capability: string; allowed: boolean }> = []

    for (const [capability, allowed] of Object.entries(edited)) {
      if (original[capability] !== allowed) {
        changes.push({ capability, allowed })
      }
    }

    if (changes.length > 0) {
      await updatePermissions.mutateAsync({
        groupId,
        request: { permissions: changes },
      })
      await refetch()
    }
  }

  // Save all changes
  const handleSaveAll = async () => {
    if (!permissionsData?.permissions) return

    for (const group of groups) {
      const original = permissionsData.permissions[group.id] || {}
      const edited = editedPermissions[group.id] || {}
      const changes: Array<{ capability: string; allowed: boolean }> = []

      for (const [capability, allowed] of Object.entries(edited)) {
        if (original[capability] !== allowed) {
          changes.push({ capability, allowed })
        }
      }

      if (changes.length > 0) {
        await updatePermissions.mutateAsync({
          groupId: group.id,
          request: { permissions: changes },
        })
      }
    }
    await refetch()
  }

  // Open copy dialog
  const openCopyDialog = (targetGroupId: number) => {
    setCopyTargetGroupId(targetGroupId)
    setCopySourceGroupId('')
    setShowCopyDialog(true)
  }

  // Handle copy confirm
  const handleCopyConfirm = async () => {
    if (!copyTargetGroupId || !copySourceGroupId) return
    await copyPermissions.mutateAsync({
      targetGroupId: copyTargetGroupId,
      sourceGroupId: parseInt(copySourceGroupId, 10),
    })
    await refetch()
    setShowCopyDialog(false)
  }

  // Discard changes
  const handleDiscard = () => {
    if (permissionsData?.permissions) {
      setEditedPermissions(permissionsData.permissions)
    }
  }

  // Check if group has any changes
  const groupHasChanges = (groupId: number) => {
    if (!permissionsData?.permissions) return false
    const original = permissionsData.permissions[groupId] || {}
    const edited = editedPermissions[groupId] || {}

    for (const [cap, allowed] of Object.entries(edited)) {
      if (original[cap] !== allowed) return true
    }
    return false
  }

  const isLoading = loadingCaps || loadingGroups || loadingPerms

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
          <h2 className="text-lg font-semibold text-white">Group Permissions</h2>
          <p className="mt-1 text-sm text-gray-400">
            Customize what each group can do in the system
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        </div>
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
              onClick={handleSaveAll}
              disabled={updatePermissions.isPending}
            >
              {updatePermissions.isPending ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              Save All Changes
            </Button>
          </div>
        </div>
      )}

      {/* Permission matrix */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-gray-700">
              <th className="min-w-[250px] p-3 text-left text-sm font-medium text-gray-400">
                Capability
              </th>
              {groups.map((group) => (
                <th key={group.id} className="w-32 p-3 text-center">
                  <div className="flex flex-col items-center gap-1">
                    <div className="flex items-center gap-1">
                      <Users className="h-4 w-4 text-blue-400" />
                      {group.is_system && (
                        <span title="System group">
                          <Lock className="h-3 w-3 text-gray-500" />
                        </span>
                      )}
                    </div>
                    <span className="text-sm font-medium text-gray-300">
                      {group.name}
                    </span>
                    <div className="mt-1 flex gap-1">
                      <button
                        onClick={() => openCopyDialog(group.id)}
                        className="rounded px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-700 hover:text-gray-300"
                        title="Copy permissions from another group"
                      >
                        <Copy className="h-3 w-3" />
                      </button>
                      {groupHasChanges(group.id) && (
                        <button
                          onClick={() => handleSaveGroup(group.id)}
                          disabled={updatePermissions.isPending}
                          className="rounded bg-blue-600/50 px-1.5 py-0.5 text-xs text-blue-300 hover:bg-blue-600"
                        >
                          Save
                        </button>
                      )}
                    </div>
                  </div>
                </th>
              ))}
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
                groups={groups}
                editedPermissions={editedPermissions}
                onPermissionToggle={handleToggle}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Copy permissions dialog */}
      <Dialog open={showCopyDialog} onOpenChange={setShowCopyDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Copy Permissions</DialogTitle>
            <DialogDescription>
              Copy all permissions from another group to{' '}
              <strong>{groups.find((g) => g.id === copyTargetGroupId)?.name}</strong>.
              This will overwrite all current permissions for this group.
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <Select value={copySourceGroupId} onValueChange={setCopySourceGroupId}>
              <SelectTrigger>
                <SelectValue placeholder="Select source group" />
              </SelectTrigger>
              <SelectContent>
                {groups
                  .filter((g) => g.id !== copyTargetGroupId)
                  .map((group) => (
                    <SelectItem key={group.id} value={group.id.toString()}>
                      {group.name}
                      {group.is_system && ' (System)'}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCopyDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCopyConfirm}
              disabled={!copySourceGroupId || copyPermissions.isPending}
            >
              {copyPermissions.isPending && (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              )}
              Copy Permissions
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
  groups: Group[]
  editedPermissions: Record<number, Record<string, boolean>>
  onPermissionToggle: (groupId: number, capability: string) => void
}

function CategorySection({
  category,
  capabilities,
  expanded,
  onToggle,
  groups,
  editedPermissions,
  onPermissionToggle,
}: CategorySectionProps) {
  return (
    <>
      {/* Category header row */}
      <tr
        className="cursor-pointer border-b border-gray-800 bg-gray-900/50 hover:bg-gray-800/50"
        onClick={onToggle}
      >
        <td className="p-3" colSpan={1 + groups.length}>
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
            {groups.map((group) => {
              const isAllowed = editedPermissions[group.id]?.[cap.capability] ?? false

              return (
                <td key={group.id} className="p-3 text-center">
                  <button
                    onClick={() => onPermissionToggle(group.id, cap.capability)}
                    className={`
                      inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors
                      ${
                        isAllowed
                          ? 'bg-green-900/50 text-green-400 hover:bg-green-800/50'
                          : 'bg-gray-800 text-gray-500 hover:bg-gray-700'
                      }
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
