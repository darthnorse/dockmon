/**
 * TagChip Component - Phase 3d
 *
 * FEATURES:
 * - Displays tag with color generated from hash
 * - Clickable to filter by tag (optional)
 * - Removable in edit mode (× icon)
 * - Tooltip shows host/container count
 *
 * COLOR GENERATION:
 * - Uses HSL color space with fixed saturation/lightness
 * - Hue derived from tag name hash (0-360°)
 * - Provides consistent color per tag name
 *
 * USAGE:
 * ```tsx
 * <TagChip tag="production" onClick={() => filterByTag('production')} />
 * <TagChip tag="compose:frontend" onRemove={() => removeTag('compose:frontend')} />
 * ```
 */

import { X } from 'lucide-react'

export interface TagChipProps {
  /** Tag name to display */
  tag: string
  /** Optional click handler for filtering */
  onClick?: () => void
  /** Optional remove handler for edit mode */
  onRemove?: () => void
  /** Optional tooltip text (defaults to tag name) */
  tooltip?: string
  /** Size variant */
  size?: 'sm' | 'md'
}

/**
 * Generate consistent color from tag name using hash
 * Formula: hash all characters → modulo 360 for hue
 * Returns HSL color with fixed saturation (50%) and lightness (45%)
 */
function tagColor(tag: string): string {
  const hash = [...tag].reduce((acc, char) => acc + char.charCodeAt(0), 0)
  const hue = hash % 360
  return `hsl(${hue}, 50%, 45%)`
}

export function TagChip({
  tag,
  onClick,
  onRemove,
  tooltip,
  size = 'sm',
}: TagChipProps) {
  const color = tagColor(tag)
  const isClickable = !!onClick
  const isRemovable = !!onRemove

  const sizeClasses = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-3 py-1 text-sm',
  }

  return (
    <span
      className={`
        inline-flex items-center gap-1 rounded-full font-medium
        ${sizeClasses[size]}
        ${isClickable ? 'cursor-pointer hover:opacity-80 transition-opacity' : ''}
      `}
      style={{
        backgroundColor: color,
        color: '#ffffff',
      }}
      onClick={onClick}
      title={tooltip || tag}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      onKeyDown={isClickable ? (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick?.()
        }
      } : undefined}
    >
      <span>{tag}</span>
      {isRemovable && (
        <button
          type="button"
          className="ml-0.5 hover:bg-black/20 rounded-full p-0.5 transition-colors"
          onClick={(e) => {
            e.stopPropagation() // Prevent tag click when removing
            onRemove()
          }}
          aria-label={`Remove ${tag} tag`}
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </span>
  )
}
