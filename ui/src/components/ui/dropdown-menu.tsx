/**
 * Dropdown Menu Component
 * Simple menu for host/container actions
 */

import * as React from 'react'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'

interface DropdownMenuProps {
  trigger: React.ReactNode
  children: React.ReactNode
  align?: 'start' | 'end'
}

export function DropdownMenu({ trigger, children, align = 'end' }: DropdownMenuProps) {
  const [open, setOpen] = React.useState(false)
  const triggerRef = React.useRef<HTMLDivElement>(null)
  const menuRef = React.useRef<HTMLDivElement>(null)
  const [position, setPosition] = React.useState({ top: 0, left: 0, right: 0 })

  React.useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(event.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(event.target as Node)
      ) {
        setOpen(false)
      }
    }

    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
    return undefined
  }, [open])

  // Calculate position when opened
  React.useEffect(() => {
    if (open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect()
      setPosition({
        top: rect.bottom + 4,
        left: rect.left,
        right: window.innerWidth - rect.right,
      })
    }
  }, [open])

  return (
    <>
      <div className="relative inline-block" ref={triggerRef}>
        <div onClick={(e) => { e.stopPropagation(); setOpen(!open) }}>{trigger}</div>
      </div>
      {open &&
        createPortal(
          <div
            ref={menuRef}
            className={cn(
              'fixed z-[9999] min-w-[180px] rounded-md border border-border bg-popover text-popover-foreground p-1 shadow-xl',
            )}
            style={{
              top: `${position.top}px`,
              ...(align === 'end' ? { right: `${position.right}px` } : { left: `${position.left}px` }),
            }}
          >
            <div onClick={(e) => { e.stopPropagation(); setOpen(false) }}>{children}</div>
          </div>,
          document.body
        )}
    </>
  )
}

interface DropdownMenuItemProps {
  onClick?: () => void
  icon?: React.ReactNode
  children: React.ReactNode
  destructive?: boolean
  disabled?: boolean
}

export function DropdownMenuItem({
  onClick,
  icon,
  children,
  destructive,
  disabled,
}: DropdownMenuItemProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'relative flex w-full cursor-pointer select-none items-center gap-1.5 rounded-sm px-2 py-1 text-xs outline-none transition-colors',
        disabled
          ? 'pointer-events-none opacity-50'
          : destructive
            ? 'hover:bg-destructive/10 hover:text-destructive focus:bg-destructive/10 focus:text-destructive'
            : 'hover:bg-accent focus:bg-accent'
      )}
    >
      {icon && <span className="w-3.5 h-3.5 flex items-center justify-center">{icon}</span>}
      <span>{children}</span>
    </button>
  )
}

export function DropdownMenuSeparator() {
  return <div className="my-1 h-px bg-border" />
}
