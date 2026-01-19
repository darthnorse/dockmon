/**
 * ConfirmModal Component
 *
 * A reusable confirmation modal for destructive or important actions.
 * Provides consistent styling and behavior across the application.
 */

import { ReactNode, useId, useEffect, useRef } from 'react'
import { AlertTriangle, Info, AlertCircle } from 'lucide-react'

type ConfirmVariant = 'danger' | 'warning' | 'info'

interface ConfirmModalProps {
  isOpen: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  description?: string
  children?: ReactNode
  confirmText?: string
  cancelText?: string
  pendingText?: string
  variant?: ConfirmVariant
  isPending?: boolean
  disabled?: boolean
}

const VARIANT_CONFIG: Record<ConfirmVariant, {
  icon: typeof AlertTriangle
  iconBgClass: string
  iconClass: string
  buttonClass: string
}> = {
  danger: {
    icon: AlertCircle,
    iconBgClass: 'bg-danger/10',
    iconClass: 'text-danger',
    buttonClass: 'bg-danger text-danger-foreground hover:bg-danger/90',
  },
  warning: {
    icon: AlertTriangle,
    iconBgClass: 'bg-warning/10',
    iconClass: 'text-warning',
    buttonClass: 'bg-warning text-warning-foreground hover:bg-warning/90',
  },
  info: {
    icon: Info,
    iconBgClass: 'bg-info/10',
    iconClass: 'text-info',
    buttonClass: 'bg-accent text-accent-foreground hover:bg-accent/90',
  },
}

export function ConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  children,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  pendingText = 'Processing...',
  variant = 'warning',
  isPending = false,
  disabled = false,
}: ConfirmModalProps) {
  const titleId = useId()
  const descriptionId = useId()
  const cancelButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!isOpen) return

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isPending) {
        onClose()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, isPending, onClose])

  useEffect(() => {
    if (isOpen && cancelButtonRef.current) {
      cancelButtonRef.current.focus()
    }
  }, [isOpen])

  if (!isOpen) return null

  const config = VARIANT_CONFIG[variant]
  const Icon = config.icon

  const handleBackdropClick = () => {
    if (!isPending) {
      onClose()
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" data-testid="confirm-modal-backdrop">
      <div
        className="absolute inset-0 bg-black/50"
        onClick={handleBackdropClick}
        aria-hidden="true"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        className="relative bg-surface-1 rounded-lg shadow-xl border border-border max-w-md w-full mx-4"
        data-testid="confirm-modal"
      >
        <div className="px-6 py-4 border-b border-border">
          <div className="flex items-center gap-3">
            <div className={`flex items-center justify-center h-8 w-8 rounded-full ${config.iconBgClass}`}>
              <Icon className={`h-5 w-5 ${config.iconClass}`} aria-hidden="true" />
            </div>
            <div>
              <h2 id={titleId} className="text-lg font-semibold text-foreground">
                {title}
              </h2>
              {description && (
                <p id={descriptionId} className="text-sm text-muted-foreground mt-1">
                  {description}
                </p>
              )}
            </div>
          </div>
        </div>

        {children && (
          <div className="px-6 py-4">
            {children}
          </div>
        )}

        <div className="px-6 py-4 border-t border-border flex items-center justify-end gap-2">
          <button
            ref={cancelButtonRef}
            onClick={onClose}
            disabled={isPending}
            className="px-4 py-2 text-sm font-medium text-foreground hover:bg-surface-2 rounded transition-colors disabled:opacity-50"
            data-testid="confirm-modal-cancel"
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            disabled={isPending || disabled}
            className={`px-4 py-2 text-sm font-medium rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${config.buttonClass}`}
            data-testid="confirm-modal-confirm"
          >
            {isPending ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin h-4 w-4 border-2 rounded-full border-current border-t-transparent" aria-hidden="true" />
                {pendingText}
              </span>
            ) : (
              confirmText
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
