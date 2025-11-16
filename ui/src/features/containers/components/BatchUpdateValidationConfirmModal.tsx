/**
 * Batch Update Validation Confirmation Modal
 *
 * Displays a confirmation dialog when attempting bulk update that includes
 * containers matching validation patterns (WARN level).
 *
 * Shows:
 * - Allowed containers (will update without issues)
 * - Warned containers (matched patterns, require confirmation)
 * - Blocked containers (excluded from update)
 */

import { AlertTriangle, CheckCircle, XCircle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface ValidationCategory {
  container_id: string
  container_name: string
  reason: string
  matched_pattern?: string
}

interface BatchUpdateValidationConfirmModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => void
  allowed: ValidationCategory[]
  warned: ValidationCategory[]
  blocked: ValidationCategory[]
}

export function BatchUpdateValidationConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  allowed,
  warned,
  blocked
}: BatchUpdateValidationConfirmModalProps) {
  if (!isOpen) return null

  const totalContainers = allowed.length + warned.length + blocked.length
  const totalWillUpdate = allowed.length + warned.length

  const handleConfirm = () => {
    onConfirm()
    onClose()
  }

  // Prevent event bubbling to backdrop
  const handleModalClick = (e: React.MouseEvent) => {
    e.stopPropagation()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal Container */}
      <div
        className="relative bg-surface-1 rounded-lg shadow-xl border border-border max-w-2xl w-full max-h-[80vh] flex flex-col"
        onClick={handleModalClick}
        role="dialog"
        aria-modal="true"
        aria-labelledby="batch-validation-modal-title"
      >
        {/* Header */}
        <div className="p-6 pb-4 border-b border-border">
          <div className="flex items-start gap-4">
            <div className="flex-shrink-0 text-yellow-400">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <div className="flex-1">
              <h2
                id="batch-validation-modal-title"
                className="text-lg font-semibold text-text-primary"
              >
                Confirm Bulk Container Update
              </h2>
              <p className="mt-1 text-sm text-text-secondary">
                {totalContainers} container{totalContainers !== 1 ? 's' : ''} selected
              </p>
            </div>
          </div>
        </div>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Summary */}
          <div className="bg-surface-2 rounded-md p-4 border border-border/50">
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <div className="text-2xl font-bold text-success">{allowed.length}</div>
                <div className="text-xs text-text-tertiary">Allowed</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-warning">{warned.length}</div>
                <div className="text-xs text-text-tertiary">Warned</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-danger">{blocked.length}</div>
                <div className="text-xs text-text-tertiary">Blocked</div>
              </div>
            </div>
          </div>

          {/* Warning about blocked containers */}
          {blocked.length > 0 && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-md p-3">
              <div className="flex items-start gap-2">
                <XCircle className="h-4 w-4 text-red-400 mt-0.5 flex-shrink-0" />
                <div className="text-xs text-red-200/90">
                  <strong>{blocked.length} container{blocked.length !== 1 ? 's' : ''}</strong> will be excluded from this update (blocked by policy)
                </div>
              </div>
            </div>
          )}

          {/* Warning about warned containers */}
          {warned.length > 0 && (
            <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-md p-3">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-yellow-400 mt-0.5 flex-shrink-0" />
                <div className="text-xs text-yellow-200/90">
                  <strong>{warned.length} container{warned.length !== 1 ? 's' : ''}</strong> matched warning patterns. Review carefully before proceeding.
                </div>
              </div>
            </div>
          )}

          {/* Allowed Containers */}
          {allowed.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle className="h-4 w-4 text-success" />
                <h3 className="text-sm font-medium text-text-primary">
                  Allowed ({allowed.length})
                </h3>
              </div>
              <div className="bg-surface-2 rounded-md border border-border/50 divide-y divide-border/50 max-h-32 overflow-y-auto">
                {allowed.map((container) => (
                  <div key={container.container_id} className="px-3 py-2">
                    <div className="text-xs font-medium text-text-primary">
                      {container.container_name}
                    </div>
                    <div className="text-xs text-text-tertiary">{container.reason}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Warned Containers */}
          {warned.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="h-4 w-4 text-warning" />
                <h3 className="text-sm font-medium text-text-primary">
                  Warned ({warned.length})
                </h3>
              </div>
              <div className="bg-surface-2 rounded-md border border-yellow-500/20 divide-y divide-border/50 max-h-48 overflow-y-auto">
                {warned.map((container) => (
                  <div key={container.container_id} className="px-3 py-2">
                    <div className="text-xs font-medium text-text-primary">
                      {container.container_name}
                    </div>
                    <div className="text-xs text-text-secondary mt-1">{container.reason}</div>
                    {container.matched_pattern && (
                      <div className="flex items-center gap-1 mt-1">
                        <span className="text-xs text-text-tertiary">Pattern:</span>
                        <span className="text-xs font-mono text-yellow-400 bg-surface-3 px-1.5 py-0.5 rounded">
                          {container.matched_pattern}
                        </span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Blocked Containers */}
          {blocked.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <XCircle className="h-4 w-4 text-danger" />
                <h3 className="text-sm font-medium text-text-primary">
                  Blocked ({blocked.length})
                </h3>
              </div>
              <div className="bg-surface-2 rounded-md border border-red-500/20 divide-y divide-border/50 max-h-32 overflow-y-auto">
                {blocked.map((container) => (
                  <div key={container.container_id} className="px-3 py-2">
                    <div className="text-xs font-medium text-text-primary">
                      {container.container_name}
                    </div>
                    <div className="text-xs text-text-secondary mt-1">{container.reason}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommendation */}
          <div className="bg-blue-500/10 border border-blue-500/20 rounded-md p-3">
            <div className="flex items-start gap-2">
              <Info className="h-4 w-4 text-blue-400 mt-0.5 flex-shrink-0" />
              <div className="text-xs text-blue-200/90">
                <strong>Recommendation:</strong> Review warned containers carefully. Ensure you have recent backups before proceeding. Blocked containers will not be updated.
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-surface-2 rounded-b-lg border-t border-border flex justify-between items-center">
          <div className="text-xs text-text-tertiary">
            {totalWillUpdate} container{totalWillUpdate !== 1 ? 's' : ''} will be updated
          </div>
          <div className="flex gap-3">
            <Button variant="outline" onClick={onClose} className="min-w-[100px]">
              Cancel
            </Button>
            <Button
              variant="default"
              onClick={handleConfirm}
              className="min-w-[120px] bg-yellow-600 hover:bg-yellow-700 text-white"
              disabled={totalWillUpdate === 0}
            >
              Update Anyway
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
