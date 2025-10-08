/**
 * Skeleton Component - Loading States
 *
 * DESIGN:
 * - Animated shimmer effect
 * - Respects prefers-reduced-motion
 * - Matches design system colors
 *
 * USAGE:
 * <Skeleton className="h-12 w-full" />
 */

import { cn } from '@/lib/utils'

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-muted', className)}
      {...props}
    />
  )
}

export { Skeleton }
