/**
 * IpChip - Displays an IP address as a styled monospace chip.
 */

interface IpChipProps {
  ip: string
  /** "sm" for compact contexts (tables), "md" for detail views (default) */
  size?: 'sm' | 'md'
}

export function IpChip({ ip, size = 'md' }: IpChipProps) {
  const sizeClasses = size === 'sm'
    ? 'text-xs px-1.5'
    : 'text-sm px-2'

  return (
    <span className={`font-mono bg-muted py-0.5 rounded ${sizeClasses}`}>
      {ip}
    </span>
  )
}
