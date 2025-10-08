/**
 * Input Component - shadcn/ui
 *
 * DESIGN SYSTEM:
 * - Input bg: #12141C → focus #151827
 * - Border: #2A2E3E → focus #3B82F6
 * - Radius: rounded-lg (8px)
 * - Label: text-gray-400 text-xs
 */

import * as React from 'react'

import { cn } from '@/lib/utils'

export interface InputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          'flex h-9 w-full rounded-lg border border-border-color bg-input px-3 py-1 text-sm shadow-sm transition-colors',
          'text-white', // White text for proper contrast on dark input background
          'file:border-0 file:bg-transparent file:text-sm file:font-medium',
          'placeholder:text-gray-400', // Grey placeholder text
          'focus-visible:outline-none focus-visible:border-primary focus-visible:ring-1 focus-visible:ring-primary',
          'disabled:cursor-not-allowed disabled:opacity-50',
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = 'Input'

export { Input }
