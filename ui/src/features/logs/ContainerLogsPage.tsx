/**
 * ContainerLogsPage - Multi-container log viewer page
 *
 * Features:
 * - Multi-select dropdown (up to 15 containers)
 * - Grouped by host
 * - Real-time streaming (polls every 1-2s)
 * - Color-coded container names
 * - All LogViewer features (search, filter, download, etc.)
 */

import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, FileText } from 'lucide-react'
import { LogViewer } from '@/components/logs/LogViewer'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import { toast } from 'sonner'
import type { Container } from '@/features/containers/types'

interface ContainerSelection {
  hostId: string
  containerId: string
  name: string
}

interface Host {
  id: string
  name: string
  address: string
}

export function ContainerLogsPage() {
  // Fetch hosts list
  const { data: hosts = [] } = useQuery<Host[]>({
    queryKey: ['hosts'],
    queryFn: () => apiClient.get('/hosts'),
  })

  // Fetch all containers
  const { data: allContainers = [] } = useQuery<Container[]>({
    queryKey: ['containers'],
    queryFn: () => apiClient.get('/containers'),
  })

  const [selectedContainers, setSelectedContainers] = useState<ContainerSelection[]>([])
  const [dropdownOpen, setDropdownOpen] = useState(false)

  // Group containers by host
  const containersByHost = allContainers.reduce<Record<string, Container[]>>((acc, container) => {
    const hostId = container.host_id
    if (hostId) {
      if (!acc[hostId]) {
        acc[hostId] = []
      }
      acc[hostId].push(container)
    }
    return acc
  }, {})

  // Sort hosts by name
  const sortedHosts = [...hosts].sort((a, b) => a.name.localeCompare(b.name))

  const handleContainerToggle = (hostId: string, containerId: string, name: string, checked: boolean) => {
    if (checked) {
      // Check if we're at the 15 container limit
      if (selectedContainers.length >= 15) {
        toast.error('Maximum 15 containers can be selected at once')
        return
      }

      setSelectedContainers((prev) => [...prev, { hostId, containerId, name }])
    } else {
      setSelectedContainers((prev) =>
        prev.filter((c) => !(c.hostId === hostId && c.containerId === containerId))
      )
    }
  }

  const isContainerSelected = (hostId: string, containerId: string) => {
    return selectedContainers.some((c) => c.hostId === hostId && c.containerId === containerId)
  }

  const getSelectionLabel = (): string => {
    if (selectedContainers.length === 0) {
      return 'Select containers to view logs...'
    } else if (selectedContainers.length === 1) {
      return selectedContainers[0]?.name || 'Unknown'
    } else {
      return `${selectedContainers.length} containers selected`
    }
  }

  const getStatusColor = (state: string): string => {
    switch (state.toLowerCase()) {
      case 'running':
        return 'text-success'
      case 'paused':
        return 'text-warning'
      case 'restarting':
        return 'text-info'
      case 'exited':
      case 'dead':
        return 'text-danger'
      default:
        return 'text-muted-foreground'
    }
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!dropdownOpen) return

    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement
      if (!target.closest('.multiselect-container')) {
        setDropdownOpen(false)
      }
    }

    document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [dropdownOpen])

  debug.log('ContainerLogsPage', 'Render', {
    hostsCount: hosts.length,
    containersCount: allContainers.length,
    selectedCount: selectedContainers.length,
  })

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="border-b border-border bg-card">
        <div className="flex items-center justify-between p-6">
          <div>
            <h1 className="text-2xl font-bold text-foreground">
              Container Logs
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              View and stream logs from up to 15 containers simultaneously
            </p>
          </div>
        </div>

        {/* Container Selection */}
        <div className="px-6 pb-4">
          <div className="multiselect-container relative max-w-2xl">
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="w-full flex items-center justify-between px-4 py-3 border border-border rounded-lg bg-background hover:bg-muted transition-colors text-left"
            >
              <span className={selectedContainers.length === 0 ? 'text-muted-foreground' : 'text-foreground'}>
                {getSelectionLabel()}
              </span>
              <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} />
            </button>

            {/* Dropdown */}
            {dropdownOpen && (
              <div className="absolute z-50 w-full mt-2 bg-card border border-border rounded-lg shadow-lg max-h-[400px] overflow-y-auto">
                {hosts.length === 0 ? (
                  <div className="p-4 text-sm text-muted-foreground text-center">
                    No hosts available. Add hosts to see containers.
                  </div>
                ) : allContainers.length === 0 ? (
                  <div className="p-4 text-sm text-muted-foreground text-center">
                    No containers available. Make sure your hosts have running containers.
                  </div>
                ) : (
                  sortedHosts.map((host) => {
                    const hostContainers = containersByHost[host.id] || []
                    if (hostContainers.length === 0) return null

                    // Sort containers by name
                    const sortedContainers = [...hostContainers].sort((a, b) =>
                      a.name.localeCompare(b.name)
                    )

                    return (
                      <div key={host.id}>
                        {/* Host Header */}
                        <div className="sticky top-0 bg-muted px-4 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b border-border">
                          {host.name}
                        </div>

                        {/* Containers */}
                        {sortedContainers.map((container) => (
                          <label
                            key={container.id}
                            className="flex items-center gap-3 px-4 py-3 hover:bg-muted cursor-pointer transition-colors border-b border-border/50 last:border-b-0"
                          >
                            <input
                              type="checkbox"
                              checked={isContainerSelected(host.id, container.id)}
                              onChange={(e) =>
                                handleContainerToggle(host.id, container.id, container.name, e.target.checked)
                              }
                              className="rounded border-border"
                            />
                            <div className="flex-1 flex items-center justify-between">
                              <span className="text-sm text-foreground">{container.name}</span>
                              <span className={`text-xs ${getStatusColor(container.state)}`}>
                                {container.state === 'running' ? '●' : '○'}
                              </span>
                            </div>
                          </label>
                        ))}
                      </div>
                    )
                  })
                )}
              </div>
            )}
          </div>

          {/* Selection Info */}
          {selectedContainers.length > 0 && (
            <div className="mt-2 text-xs text-muted-foreground">
              {selectedContainers.length} of 15 containers selected
              {selectedContainers.length >= 15 && (
                <span className="ml-2 text-warning">• Maximum limit reached</span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Log Viewer */}
      <div className="flex-1 bg-card">
        {selectedContainers.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <FileText className="w-16 h-16 mb-4 opacity-20" />
            <p className="text-lg font-medium">No containers selected</p>
            <p className="text-sm mt-2">Select one or more containers above to view their logs</p>
          </div>
        ) : (
          <LogViewer
            containers={selectedContainers}
            showContainerNames={true}
            height="calc(100vh - 280px)"
            autoRefreshDefault={true}
            showControls={true}
            compact={false}
          />
        )}
      </div>
    </div>
  )
}
