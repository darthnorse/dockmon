/**
 * ContainerLinkList Component
 *
 * Displays a list of container names as clickable buttons that open the container modal.
 * Used in Images, Networks, and Volumes tabs to show associated containers.
 */

import { useContainerModal } from '@/providers/ContainerModalProvider'

interface ContainerLinkListProps {
  containers: Array<{ id: string; name: string }>
  hostId: string
  maxVisible?: number
}

export function ContainerLinkList({
  containers,
  hostId,
  maxVisible = 3,
}: ContainerLinkListProps) {
  const { openModal } = useContainerModal()

  // Defensive: handle undefined/null containers (agent may not return this field)
  if (!containers || containers.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>
  }

  return (
    <div className="flex flex-wrap gap-1">
      {containers.slice(0, maxVisible).map((container) => {
        const shortId = container.id.slice(0, 12)
        return (
          <button
            key={shortId}
            onClick={() => openModal(`${hostId}:${shortId}`)}
            className="text-xs font-mono px-1.5 py-0.5 rounded bg-surface-3 text-foreground hover:bg-surface-3/80 transition-colors truncate max-w-[120px]"
            title={container.name}
          >
            {container.name}
          </button>
        )
      })}
      {containers.length > maxVisible && (
        <span className="text-xs text-muted-foreground px-1.5 py-0.5">
          +{containers.length - maxVisible} more
        </span>
      )}
    </div>
  )
}
