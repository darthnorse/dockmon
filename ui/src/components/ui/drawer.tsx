/**
 * Drawer Component
 *
 * Reusable slide-in drawer from the right side of the screen.
 * Features:
 * - Smooth animation (200ms ease-in-out)
 * - Overlay with click-to-close
 * - ESC key support
 * - Focus trap
 * - ARIA attributes for accessibility
 */

import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface DrawerProps {
  /**
   * Whether the drawer is open
   */
  open: boolean

  /**
   * Callback when drawer should close
   */
  onClose: () => void

  /**
   * Drawer title (can be string or ReactNode for custom content)
   */
  title: string | React.ReactNode

  /**
   * Optional subtitle
   */
  subtitle?: string

  /**
   * Drawer content
   */
  children: React.ReactNode

  /**
   * Optional width class (default: w-[600px])
   */
  width?: string

  /**
   * Optional className for the drawer content
   */
  className?: string
}

export function Drawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  width = 'w-[600px]',
  className,
}: DrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)

  // Handle ESC key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        onClose()
      }
    }

    if (open) {
      document.addEventListener('keydown', handleEscape)
      // Prevent body scroll when drawer is open
      document.body.style.overflow = 'hidden'
    }

    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  // Focus trap: focus first focusable element when drawer opens
  useEffect(() => {
    if (open && drawerRef.current) {
      const focusableElements = drawerRef.current.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      )
      const firstElement = focusableElements[0] as HTMLElement
      if (firstElement) {
        // Small delay to ensure animation starts
        setTimeout(() => firstElement.focus(), 100)
      }
    }
  }, [open])

  if (!open) return null

  return (
    <>
      {/* Overlay */}
      <div
        ref={overlayRef}
        className="fixed inset-0 bg-black/50 z-40 transition-opacity duration-200"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <div
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        className={cn(
          'fixed right-0 top-0 bottom-0 bg-surface border-l border-border z-50',
          'transform transition-transform duration-200 ease-in-out',
          'flex flex-col',
          width,
          open ? 'translate-x-0' : 'translate-x-full',
          className
        )}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-6 border-b border-border">
          <div className="flex-1 min-w-0">
            <h2 id="drawer-title" className="text-xl font-semibold truncate">
              {title}
            </h2>
            {subtitle && (
              <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="ml-4 p-2 rounded-lg hover:bg-muted transition-colors focus:outline-none focus:ring-2 focus:ring-accent"
            aria-label="Close drawer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content - scrollable */}
        <div className="flex-1 overflow-y-auto">
          {children}
        </div>
      </div>
    </>
  )
}

/**
 * DrawerSection Component
 *
 * Wrapper for sections within a drawer
 */
export interface DrawerSectionProps {
  title?: string
  children: React.ReactNode
  className?: string
}

export function DrawerSection({ title, children, className }: DrawerSectionProps) {
  return (
    <div className={cn('p-6 border-b border-border last:border-b-0', className)}>
      {title && (
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-4">
          {title}
        </h3>
      )}
      {children}
    </div>
  )
}
