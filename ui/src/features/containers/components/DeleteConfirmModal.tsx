import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import type { Container } from '../types'
import { makeCompositeKey } from '@/lib/utils/containerKeys'

interface DeleteConfirmModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: (removeVolumes: boolean) => void
  containers: Container[]
}

export function DeleteConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  containers,
}: DeleteConfirmModalProps) {
  const [removeVolumes, setRemoveVolumes] = useState(false)

  if (!isOpen) return null

  const handleConfirm = () => {
    onConfirm(removeVolumes)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-surface-1 rounded-lg shadow-xl border border-border max-w-md w-full mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center h-8 w-8 rounded-full bg-danger/10">
              <AlertTriangle className="h-5 w-5 text-danger" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-foreground">
                Delete Container{containers.length !== 1 ? 's' : ''}
              </h2>
              <p className="text-sm text-muted-foreground mt-1">
                This action cannot be undone. The container{containers.length !== 1 ? 's' : ''} and all data will be permanently deleted.
              </p>
            </div>
          </div>
        </div>

        {/* Container List */}
        <div className="px-6 py-4 overflow-y-auto flex-1 space-y-4">
          <div className="space-y-2">
            {containers.map((container) => (
              <div
                key={makeCompositeKey(container)}
                className="flex items-center gap-3 p-2 rounded bg-surface-2"
              >
                <div
                  className={`h-2 w-2 rounded-full ${
                    container.state === 'running'
                      ? 'bg-success'
                      : container.state === 'paused'
                      ? 'bg-warning'
                      : 'bg-muted-foreground'
                  }`}
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-foreground truncate">
                    {container.name}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {container.host_name || 'localhost'}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Volume removal option */}
          <div className="border-t border-border pt-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={removeVolumes}
                onChange={(e) => setRemoveVolumes(e.target.checked)}
                className="w-4 h-4 rounded border-border"
              />
              <span className="text-sm text-foreground">
                Also remove anonymous volumes
              </span>
            </label>
            <p className="text-xs text-muted-foreground mt-2">
              This will remove volumes that were created with the container but are not associated with a data volume.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-border flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-foreground hover:bg-surface-2 rounded transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            className="px-4 py-2 text-sm font-medium rounded transition-colors bg-danger text-danger-foreground hover:bg-danger/90"
          >
            Delete {containers.length} Container{containers.length !== 1 ? 's' : ''}
          </button>
        </div>
      </div>
    </div>
  )
}
