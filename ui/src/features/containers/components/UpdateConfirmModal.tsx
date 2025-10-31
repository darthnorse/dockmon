import type { Container } from '../types'
import { makeCompositeKey } from '@/lib/utils/containerKeys'

interface UpdateConfirmModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => void
  containers: Container[]
}

export function UpdateConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  containers,
}: UpdateConfirmModalProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-surface-1 rounded-lg shadow-xl border border-border max-w-md w-full mx-4 max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border">
          <h2 className="text-lg font-semibold text-foreground">
            Update Container{containers.length !== 1 ? 's' : ''}
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Are you sure you want to update {containers.length} container{containers.length !== 1 ? 's' : ''}? This will pull the latest image and recreate the container{containers.length !== 1 ? 's' : ''}.
          </p>
        </div>

        {/* Container List */}
        <div className="px-6 py-4 overflow-y-auto flex-1">
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
            onClick={onConfirm}
            className="px-4 py-2 text-sm font-medium rounded transition-colors bg-primary text-primary-foreground hover:bg-primary/90"
          >
            Update {containers.length} Container{containers.length !== 1 ? 's' : ''}
          </button>
        </div>
      </div>
    </div>
  )
}
