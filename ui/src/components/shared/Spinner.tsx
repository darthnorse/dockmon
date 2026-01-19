/**
 * Spinner Component
 *
 * A reusable loading spinner with configurable size and color variants.
 */

type SpinnerSize = 'sm' | 'md' | 'lg'
type SpinnerVariant = 'default' | 'current'

interface SpinnerProps {
  size?: SpinnerSize
  variant?: SpinnerVariant
  className?: string
}

const SIZE_CLASSES: Record<SpinnerSize, string> = {
  sm: 'h-4 w-4',
  md: 'h-6 w-6',
  lg: 'h-8 w-8',
}

const VARIANT_CLASSES: Record<SpinnerVariant, string> = {
  default: 'border-accent border-t-transparent',
  current: 'border-current border-t-transparent',
}

export function Spinner({
  size = 'md',
  variant = 'default',
  className = '',
}: SpinnerProps) {
  const sizeClass = SIZE_CLASSES[size]
  const variantClass = VARIANT_CLASSES[variant]

  return (
    <span
      className={`animate-spin border-2 rounded-full ${sizeClass} ${variantClass} ${className}`}
      aria-hidden="true"
    />
  )
}
