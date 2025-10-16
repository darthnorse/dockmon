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
}

const SelectContext = React.createContext<SelectContextType | undefined>(undefined)

export function Select({ value, onValueChange, disabled, children }: SelectProps) {
  const [open, setOpen] = React.useState(false)

  return (
    <SelectContext.Provider value={{ value, onValueChange, open, setOpen }}>
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

  const triggerRef = React.useRef<HTMLButtonElement>(null)

  return (
    <button
      id={id}
      ref={triggerRef}
      type="button"
      onClick={() => context.setOpen(!context.open)}
      className={cn(
        'flex h-9 w-full items-center justify-between rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className
      )}
    >
      {children}
      <ChevronDown className="h-4 w-4 opacity-50" />
    </button>
  )
}

export function SelectValue() {
  const context = React.useContext(SelectContext)
  if (!context) throw new Error('SelectValue must be used within Select')

  return <span>{context.value}</span>
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

  // Find the trigger button to position the dropdown
  React.useEffect(() => {
    if (context.open) {
      // Find the trigger button by looking for the button with role
      const trigger = document.querySelector('button[type="button"]') as HTMLElement
      if (trigger) {
        const rect = trigger.getBoundingClientRect()
        setPosition({
          top: rect.bottom + 4,
          left: rect.left,
          width: rect.width,
        })
      }
    }
  }, [context.open])

  // Handle click outside
  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        // Check if click is on trigger
        const trigger = (event.target as HTMLElement).closest('button[type="button"]')
        if (!trigger) {
          context.setOpen(false)
        }
      }
    }

    if (context.open) {
      // Use timeout to avoid immediate close
      setTimeout(() => {
        document.addEventListener('mousedown', handleClickOutside)
      }, 0)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
    return undefined
  }, [context, context.open])

  return createPortal(
    <div
      ref={menuRef}
      className="fixed z-[9999] rounded-md border border-border bg-popover text-popover-foreground p-1 shadow-xl max-h-[300px] overflow-auto"
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
