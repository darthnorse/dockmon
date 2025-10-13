/**
 * AlertRulesPage Component
 *
 * Manage alert rules with CRUD operations
 */

import { useState } from 'react'
import { useAlertRules, useDeleteAlertRule, useToggleAlertRule } from './hooks/useAlertRules'
import type { AlertRule } from '@/types/alerts'
import { Plus, Settings, Trash2, Power, PowerOff, Edit, AlertTriangle } from 'lucide-react'
import { AlertRuleFormModal } from './components/AlertRuleFormModal'

export function AlertRulesPage() {
  const { data: rulesData, isLoading } = useAlertRules()
  const deleteRule = useDeleteAlertRule()
  const toggleRule = useToggleAlertRule()

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [editingRule, setEditingRule] = useState<AlertRule | null>(null)
  const [deletingRuleId, setDeletingRuleId] = useState<string | null>(null)

  const rules = rulesData?.rules ?? []

  const handleToggleEnabled = async (rule: AlertRule) => {
    await toggleRule.mutateAsync({ ruleId: rule.id, enabled: !rule.enabled })
  }

  const handleDelete = async () => {
    if (!deletingRuleId) return
    await deleteRule.mutateAsync(deletingRuleId)
    setDeletingRuleId(null)
  }

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'bg-red-100 text-red-700 border-red-200'
      case 'error':
        return 'bg-orange-100 text-orange-700 border-orange-200'
      case 'warning':
        return 'bg-yellow-100 text-yellow-700 border-yellow-200'
      case 'info':
        return 'bg-blue-100 text-blue-700 border-blue-200'
      default:
        return 'bg-gray-100 text-gray-700 border-gray-200'
    }
  }

  const getScopeColor = (scope: string) => {
    switch (scope) {
      case 'host':
        return 'bg-purple-100 text-purple-700'
      case 'container':
        return 'bg-blue-100 text-blue-700'
      case 'group':
        return 'bg-green-100 text-green-700'
      default:
        return 'bg-gray-100 text-gray-700'
    }
  }

  return (
    <div className="flex h-full flex-col bg-[#0a0e14]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-800 bg-[#0d1117] px-6 py-4">
        <div>
          <h1 className="text-xl font-semibold text-white">Alert Rules</h1>
          <p className="text-sm text-gray-400">Configure rules that trigger alerts based on metrics and conditions</p>
        </div>

        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          Create Rule
        </button>
      </div>

      {/* Rules List */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-gray-400">Loading rules...</div>
        ) : rules.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-gray-400">
            <Settings className="mb-2 h-12 w-12" />
            <p className="text-lg">No alert rules configured</p>
            <p className="text-sm">Create your first rule to start monitoring</p>
          </div>
        ) : (
          <div className="p-6">
            <div className="grid gap-4">
              {rules.map((rule) => (
                <div
                  key={rule.id}
                  className={`rounded-lg border bg-[#0d1117] p-4 transition-opacity ${
                    rule.enabled ? 'border-gray-700' : 'border-gray-800 opacity-60'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    {/* Rule Info */}
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <h3 className="text-lg font-semibold text-white">{rule.name}</h3>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium border ${getSeverityColor(rule.severity)}`}>
                          {rule.severity}
                        </span>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${getScopeColor(rule.scope)}`}>
                          {rule.scope}
                        </span>
                        <span className="rounded-full bg-gray-800 px-2 py-0.5 text-xs font-medium text-gray-300">
                          {rule.kind}
                        </span>
                        {!rule.enabled && (
                          <span className="rounded-full bg-gray-700 px-2 py-0.5 text-xs font-medium text-gray-400">
                            Disabled
                          </span>
                        )}
                      </div>

                      {rule.description && <p className="text-sm text-gray-400 mb-3">{rule.description}</p>}

                      {/* Rule Details */}
                      <div className="flex flex-wrap gap-4 text-xs text-gray-500">
                        {rule.metric && rule.threshold && (
                          <span>
                            Metric: {rule.metric} {rule.operator} {rule.threshold}
                          </span>
                        )}
                        {rule.duration_seconds && (
                          <span>
                            Duration: {rule.duration_seconds}s
                          </span>
                        )}
                        {rule.occurrences && <span>Occurrences: {rule.occurrences}</span>}
                        {rule.cooldown_seconds > 0 && <span>Cooldown: {rule.cooldown_seconds}s</span>}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2 ml-4">
                      <button
                        onClick={() => handleToggleEnabled(rule)}
                        className={`rounded-md p-2 transition-colors ${
                          rule.enabled
                            ? 'text-green-500 hover:bg-gray-800'
                            : 'text-gray-500 hover:bg-gray-800 hover:text-gray-300'
                        }`}
                        title={rule.enabled ? 'Disable rule' : 'Enable rule'}
                      >
                        {rule.enabled ? <Power className="h-4 w-4" /> : <PowerOff className="h-4 w-4" />}
                      </button>

                      <button
                        onClick={() => setEditingRule(rule)}
                        className="rounded-md p-2 text-gray-400 transition-colors hover:bg-gray-800 hover:text-white"
                        title="Edit rule"
                      >
                        <Edit className="h-4 w-4" />
                      </button>

                      <button
                        onClick={() => setDeletingRuleId(rule.id)}
                        className="rounded-md p-2 text-gray-400 transition-colors hover:bg-gray-800 hover:text-red-400"
                        title="Delete rule"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Create/Edit Modal */}
      {(showCreateModal || editingRule) && (
        <AlertRuleFormModal
          rule={editingRule}
          onClose={() => {
            setShowCreateModal(false)
            setEditingRule(null)
          }}
        />
      )}

      {/* Delete Confirmation */}
      {deletingRuleId && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-md rounded-lg border border-gray-700 bg-[#0d1117] p-6 shadow-2xl">
            <div className="mb-4 flex items-start gap-4">
              <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-red-500/10">
                <AlertTriangle className="h-6 w-6 text-red-500" />
              </div>
              <div className="flex-1">
                <h3 className="mb-2 text-lg font-semibold text-white">Delete Alert Rule</h3>
                <p className="text-sm text-gray-400">
                  Are you sure you want to delete this rule? This action cannot be undone. Existing alerts created by
                  this rule will remain.
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => setDeletingRuleId(null)}
                className="rounded-md bg-gray-800 px-4 py-2 text-gray-300 transition-colors hover:bg-gray-700"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={deleteRule.isPending}
                className="rounded-md bg-red-600 px-4 py-2 text-white transition-colors hover:bg-red-700 disabled:opacity-50"
              >
                {deleteRule.isPending ? 'Deleting...' : 'Delete Rule'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
