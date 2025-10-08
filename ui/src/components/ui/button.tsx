/**
 * Button Component - shadcn/ui
 *
 * ARCHITECTURE:
 * - Radix UI Slot for composition
 * - CVA (class-variance-authority) for variants
 * - Fully accessible (WCAG 2.1 AA)
 * - Design system compliant
 */

import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const buttonVariants = cva(
  // Base styles (always applied)
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        // Primary: bg #3B82F6 → hover #2563EB
        default:
          'bg-primary text-primary-foreground shadow hover:bg-primary/90',
        // Destructive: bg #EF4444 → hover #DC2626
        destructive:
          'bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90',
        // Outline/Secondary: bg #1F2230 → hover #25293A
        outline:
          'border border-border-color bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80',
        // Secondary (alias for outline)
        secondary:
          'bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80',
        // Ghost: transparent → hover bg #171925
        ghost: 'hover:bg-surface-1 hover:text-foreground',
        // Link: underline on hover
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 py-2', // md: 36px
        sm: 'h-8 rounded-lg px-3 text-xs', // sm: 28px
        lg: 'h-11 rounded-xl px-8', // lg: 44px
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = 'Button'

export { Button, buttonVariants }
