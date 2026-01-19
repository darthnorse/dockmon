/**
 * StatusBadge Component
 *
 * A reusable status badge with configurable variants for consistent styling.
 */

import { ReactNode } from 'react'

type BadgeVariant = 'success' | 'warning' | 'danger' | 'muted' | 'info'

interface StatusBadgeProps {
  variant: BadgeVariant
  children: ReactNode
  icon?: ReactNode
}

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  danger: 'bg-danger/10 text-danger',
  muted: 'bg-muted/30 text-muted-foreground',
  info: 'bg-info/10 text-info',
}

export function StatusBadge({ variant, children, icon }: StatusBadgeProps) {
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded-full ${VARIANT_CLASSES[variant]}`}>
      {icon}
      {children}
    </span>
  )
}
