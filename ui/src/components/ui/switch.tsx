import * as React from 'react'

export interface SwitchProps {
  id?: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
  className?: string
}

export const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ id, checked, onCheckedChange, disabled = false, className = '' }, ref) => {
    return (
      <button
        id={id}
        ref={ref}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => !disabled && onCheckedChange(!checked)}
        className={`
          relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent
          transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent
          focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50
          ${checked ? 'bg-accent' : 'bg-border'}
          ${className}
        `}
      >
        <span
          className={`
            pointer-events-none block h-5 w-5 rounded-full bg-white shadow-lg ring-0
            transition-transform
            ${checked ? 'translate-x-5' : 'translate-x-0'}
          `}
        />
      </button>
    )
  }
)

Switch.displayName = 'Switch'
