/**
 * No Channels Confirmation Modal
 *
 * Displays a warning when attempting to create/edit an alert rule
 * without any notification channels selected.
 */

import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface NoChannelsConfirmModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => void
  hasConfiguredChannels: boolean
}

export function NoChannelsConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  hasConfiguredChannels
}: NoChannelsConfirmModalProps) {
  if (!isOpen) return null

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
      {/* Backdrop - clickable to close */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal Container */}
      <div
        className="relative bg-surface-1 rounded-lg shadow-xl border border-border max-w-md w-full"
        onClick={handleModalClick}
        role="dialog"
        aria-modal="true"
        aria-labelledby="no-channels-modal-title"
      >
        {/* Header */}
        <div className="p-6 pb-4">
          <div className="flex items-start gap-4">
            <div className="flex-shrink-0 text-yellow-400">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <div className="flex-1">
              <h2
                id="no-channels-modal-title"
                className="text-lg font-semibold text-text-primary"
              >
                No Notification Channels Selected
              </h2>
              <p className="mt-1 text-sm text-text-secondary">
                This rule will not send any notifications
              </p>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 pb-4">
          <div className="bg-surface-2 rounded-md p-4 border border-border/50">
            <p className="text-sm text-text-secondary mb-3">
              {hasConfiguredChannels
                ? "You haven't selected any notification channels for this alert rule."
                : "You haven't configured any notification channels in Settings."}
            </p>

            <div className="space-y-2">
              <div className="flex items-start gap-2">
                <span className="text-sm text-text-primary flex-1">
                  <strong>What this means:</strong>
                  <ul className="list-disc list-inside mt-1 space-y-1 text-text-secondary">
                    <li>Alerts will be created when conditions are met</li>
                    <li>Alerts will appear in the Alerts page</li>
                    <li>
                      <strong className="text-yellow-400">No notifications will be sent</strong>{' '}
                      (email, Telegram, etc.)
                    </li>
                  </ul>
                </span>
              </div>
            </div>
          </div>

          <div className="mt-4 bg-yellow-500/10 border border-yellow-500/20 rounded-md p-3">
            <p className="text-xs text-yellow-200/90">
              {hasConfiguredChannels ? (
                <>
                  <strong>Recommendation:</strong> Go back and select at least one notification
                  channel to receive alerts via email, Telegram, Discord, or other services.
                </>
              ) : (
                <>
                  <strong>Recommendation:</strong> Configure notification channels in Settings {'>'}{' '}
                  Notifications before creating alert rules.
                </>
              )}
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-surface-2 rounded-b-lg border-t border-border flex justify-end gap-3">
          <Button variant="outline" onClick={onClose} className="min-w-[100px]">
            Go Back
          </Button>
          <Button
            variant="default"
            onClick={handleConfirm}
            className="min-w-[120px] bg-yellow-600 hover:bg-yellow-700 text-white"
          >
            Create Anyway
          </Button>
        </div>
      </div>
    </div>
  )
}
