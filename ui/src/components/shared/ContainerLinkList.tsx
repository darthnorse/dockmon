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
}

export function ContainerLinkList({
  containers,
  hostId,
}: ContainerLinkListProps) {
  const { openModal } = useContainerModal()

  // Defensive: handle undefined/null containers (agent may not return this field)
  if (!containers || containers.length === 0) {
    return <span className="text-sm text-muted-foreground">—</span>
  }

  // No truncation: cap height + scroll so every attached container stays clickable.
  return (
    <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
      {containers.map((container) => {
        const shortId = container.id.slice(0, 12)
        return (
          <button
            key={shortId}
            onClick={() => openModal(`${hostId}:${shortId}`)}
            className="text-sm font-mono px-1.5 py-0.5 rounded bg-surface-3 text-foreground hover:bg-surface-3/80 transition-colors truncate max-w-[120px]"
            title={container.name}
          >
            {container.name}
          </button>
        )
      })}
    </div>
  )
}
