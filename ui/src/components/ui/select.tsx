/**
 * Select Component
 * Dropdown select using similar pattern to dropdown-menu
 */

import * as React from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

interface SelectProps {
  value: string
  onValueChange: (value: string) => void
  disabled?: boolean
  children: React.ReactNode
}

interface SelectContextType {
  value: string
  onValueChange: (value: string) => void
  open: boolean
  setOpen: (open: boolean) => void
  triggerRef: React.RefObject<HTMLButtonElement> | null
}

const SelectContext = React.createContext<SelectContextType | undefined>(undefined)

export function Select({ value, onValueChange, disabled, children }: SelectProps) {
  const [open, setOpen] = React.useState(false)
  const triggerRef = React.useRef<HTMLButtonElement>(null)

  return (
    <SelectContext.Provider value={{ value, onValueChange, open, setOpen, triggerRef }}>
      <div className={cn('relative', disabled && 'pointer-events-none opacity-50')}>
        {children}
      </div>
    </SelectContext.Provider>
  )
}

interface SelectTriggerProps {
  id?: string
  className?: string
  children: React.ReactNode
}

export function SelectTrigger({ id, className, children }: SelectTriggerProps) {
  const context = React.useContext(SelectContext)
  if (!context) throw new Error('SelectTrigger must be used within Select')

  return (
    <button
      id={id}
      ref={context.triggerRef}
      type="button"
      onClick={() => context.setOpen(!context.open)}
      className={cn(
        'flex h-9 w-full items-center justify-between rounded-lg border border-border-color bg-input px-3 py-2 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-50',
        className
      )}
    >
      {children}
      <ChevronDown className="h-4 w-4 opacity-50" />
    </button>
  )
}

interface SelectValueProps {
  children?: React.ReactNode
  placeholder?: string
}

export function SelectValue({ children, placeholder }: SelectValueProps = {}) {
  const context = React.useContext(SelectContext)
  if (!context) throw new Error('SelectValue must be used within Select')

  // If children provided, use that as custom render
  if (children) {
    return <span>{children}</span>
  }

  // Otherwise show value or placeholder
  return <span className={!context.value && placeholder ? 'text-muted-foreground' : ''}>
    {context.value || placeholder}
  </span>
}

interface SelectContentProps {
  children: React.ReactNode
}

export function SelectContent({ children }: SelectContentProps) {
  const context = React.useContext(SelectContext)
  if (!context) throw new Error('SelectContent must be used within Select')

  // Don't render if not open
  if (!context.open) return null

  return <SelectPortalContent>{children}</SelectPortalContent>
}

function SelectPortalContent({ children }: { children: React.ReactNode }) {
  const context = React.useContext(SelectContext)
  if (!context) return null

  const menuRef = React.useRef<HTMLDivElement>(null)
  const [position, setPosition] = React.useState({ top: 0, left: 0, width: 0 })

  // Destructure to avoid unnecessary re-runs
  const { open, setOpen, triggerRef } = context

  // Position the dropdown, measuring actual height to flip if needed
  React.useLayoutEffect(() => {
    if (open && triggerRef?.current && menuRef.current) {
      const trigger = triggerRef.current
      const menu = menuRef.current
      const triggerRect = trigger.getBoundingClientRect()
      const menuHeight = menu.offsetHeight
      const viewportHeight = window.innerHeight
      const spaceBelow = viewportHeight - triggerRect.bottom
      const spaceAbove = triggerRect.top

      // Position above if not enough space below and more space above
      const positionAbove = spaceBelow < menuHeight + 8 && spaceAbove > spaceBelow

      setPosition({
        top: positionAbove ? triggerRect.top - menuHeight - 4 : triggerRect.bottom + 4,
        left: triggerRect.left,
        width: triggerRect.width,
      })
    }
  }, [open, triggerRef, children])

  // Close dropdown on scroll (standard behavior)
  React.useEffect(() => {
    const handleScroll = () => {
      setOpen(false)
    }

    if (open) {
      // Use capture phase to catch all scroll events
      window.addEventListener('scroll', handleScroll, true)
      return () => {
        window.removeEventListener('scroll', handleScroll, true)
      }
    }

    return undefined
  }, [open, setOpen])

  // Handle click outside
  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        // Check if click is on trigger
        const trigger = (event.target as HTMLElement).closest('button[type="button"]')
        if (!trigger) {
          setOpen(false)
        }
      }
    }

    if (open) {
      // Use timeout to avoid immediate close
      const timeoutId = setTimeout(() => {
        document.addEventListener('mousedown', handleClickOutside)
      }, 0)

      return () => {
        clearTimeout(timeoutId)
        document.removeEventListener('mousedown', handleClickOutside)
      }
    }
    return undefined
  }, [open, setOpen])

  return createPortal(
    <div
      ref={menuRef}
      role="listbox"
      className="fixed z-[99999] rounded-md border border-border bg-popover text-popover-foreground p-1 shadow-xl max-h-[300px] overflow-auto pointer-events-auto"
      style={{
        top: `${position.top}px`,
        left: `${position.left}px`,
        minWidth: `${position.width}px`,
      }}
    >
      {children}
    </div>,
    document.body
  )
}

interface SelectItemProps {
  value: string
  children: React.ReactNode
}

export function SelectItem({ value, children }: SelectItemProps) {
  const context = React.useContext(SelectContext)
  if (!context) throw new Error('SelectItem must be used within Select')

  const handleClick = () => {
    context.onValueChange(value)
    context.setOpen(false)
  }

  const isSelected = context.value === value

  return (
    <button
      role="option"
      aria-selected={isSelected}
      onClick={handleClick}
      className={cn(
        'relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none transition-colors',
        isSelected ? 'bg-accent text-accent-foreground' : 'hover:bg-accent hover:text-accent-foreground'
      )}
    >
      {children}
    </button>
  )
}
