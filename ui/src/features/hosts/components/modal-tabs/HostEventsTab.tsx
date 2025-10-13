/**
 * HostEventsTab Component (with filtering)
 *
 * Events tab for host modal - Shows filtered events for specific host
 * Includes filtering by time range, severity, category, container, and search (but not host)
 */

import { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Calendar, AlertCircle, X, ArrowUpDown, Search, Check, Download } from 'lucide-react'
import { useHostEvents } from '@/hooks/useEvents'
import { EventRow } from '@/features/events/components/EventRow'

interface HostEventsTabProps {
  hostId: string
}

const TIME_RANGE_OPTIONS = [
  { value: 1, label: 'Last 1 hour' },
  { value: 6, label: 'Last 6 hours' },
  { value: 12, label: 'Last 12 hours' },
  { value: 24, label: 'Last 24 hours' },
  { value: 48, label: 'Last 48 hours' },
  { value: 168, label: 'Last 7 days' },
  { value: 720, label: 'Last 30 days' },
  { value: 0, label: 'All time' },
]

const SEVERITY_OPTIONS = ['critical', 'error', 'warning', 'info']
const CATEGORY_OPTIONS = ['container', 'host', 'system', 'network', 'volume']

export function HostEventsTab({ hostId }: HostEventsTabProps) {
  const [filters, setFilters] = useState({
    hours: 24,
    severity: '' as string,
    category: '' as string,
    search: '',
  })
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [containerSearchInput, setContainerSearchInput] = useState('')
  const [selectedContainerIds, setSelectedContainerIds] = useState<string[]>([])
  const [showContainerDropdown, setShowContainerDropdown] = useState(false)
  const containerDropdownRef = useRef<HTMLDivElement>(null)

  // TODO: Update useHostEvents to support filtering parameters
  const { data: eventsData, isLoading, error } = useHostEvents(hostId, 200)
  const allEvents = eventsData?.events ?? []

  // Fetch containers for this host
  const { data: allContainers = [] } = useQuery<any[]>({
    queryKey: ['containers'],
    queryFn: () => fetch('/api/containers').then((res) => res.json()),
  })

  // Filter to only show containers from this host
  const hostContainers = allContainers.filter((c) => c.host_id === hostId)

  // Filter containers based on search
  const filteredContainers = hostContainers.filter((c) =>
    c.name.toLowerCase().includes(containerSearchInput.toLowerCase())
  )

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerDropdownRef.current && !containerDropdownRef.current.contains(event.target as Node)) {
        setShowContainerDropdown(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Client-side filtering (TODO: move to backend)
  const filteredEvents = allEvents
    .filter((event) => {
      // Time range filter
      const eventTime = new Date(event.timestamp).getTime()
      const cutoff = Date.now() - filters.hours * 60 * 60 * 1000
      if (eventTime < cutoff) return false

      // Severity filter
      if (filters.severity && event.severity.toLowerCase() !== filters.severity.toLowerCase()) {
        return false
      }

      // Category filter
      if (filters.category && event.category?.toLowerCase() !== filters.category.toLowerCase()) {
        return false
      }

      // Container filter
      if (selectedContainerIds.length > 0 && event.container_id && !selectedContainerIds.includes(event.container_id)) {
        return false
      }

      // Search filter
      if (filters.search) {
        const searchLower = filters.search.toLowerCase()
        const titleMatch = event.title?.toLowerCase().includes(searchLower)
        const messageMatch = event.message?.toLowerCase().includes(searchLower)
        const containerMatch = event.container_name?.toLowerCase().includes(searchLower)
        if (!titleMatch && !messageMatch && !containerMatch) return false
      }

      return true
    })
    .sort((a, b) => {
      const aTime = new Date(a.timestamp).getTime()
      const bTime = new Date(b.timestamp).getTime()
      return sortOrder === 'desc' ? bTime - aTime : aTime - bTime
    })

  const updateFilter = (key: keyof typeof filters, value: any) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
  }

  const resetFilters = () => {
    setFilters({
      hours: 24,
      severity: '',
      category: '',
      search: '',
    })
    setSelectedContainerIds([])
    setContainerSearchInput('')
  }

  const toggleContainerSelection = (containerId: string) => {
    setSelectedContainerIds((prev) =>
      prev.includes(containerId) ? prev.filter((id) => id !== containerId) : [...prev, containerId]
    )
  }

  const toggleSortOrder = () => {
    setSortOrder((prev) => (prev === 'desc' ? 'asc' : 'desc'))
  }

  // Export events to CSV
  const exportToCSV = () => {
    if (filteredEvents.length === 0) return

    // CSV headers
    const headers = [
      'Timestamp',
      'Severity',
      'Category',
      'Type',
      'Title',
      'Message',
      'Container',
      'Old State',
      'New State',
    ]

    // Convert events to CSV rows
    const rows = filteredEvents.map((event) => [
      event.timestamp,
      event.severity,
      event.category || '',
      event.event_type || '',
      event.title || '',
      event.message || '',
      event.container_name || '',
      event.old_state || '',
      event.new_state || '',
    ])

    // Escape CSV values (handle quotes and commas)
    const escapeCSV = (value: string): string => {
      if (value.includes('"') || value.includes(',') || value.includes('\n')) {
        return `"${value.replace(/"/g, '""')}"`
      }
      return value
    }

    // Build CSV content
    const csvContent = [
      headers.map(escapeCSV).join(','),
      ...rows.map((row) => row.map((cell) => escapeCSV(String(cell))).join(',')),
    ].join('\n')

    // Create download link
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const link = document.createElement('a')
    const url = URL.createObjectURL(blob)
    link.setAttribute('href', url)
    link.setAttribute('download', `dockmon-host-events-${new Date().toISOString().split('T')[0]}.csv`)
    link.style.visibility = 'hidden'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    // Clean up object URL to prevent memory leak
    URL.revokeObjectURL(url)
  }

  if (isLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-muted-foreground text-sm">Loading events...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-12 w-12 mx-auto mb-3 text-red-500 opacity-50" />
          <p className="text-sm text-red-500">Failed to load events</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Filters */}
      <div className="border-b border-border bg-surface px-6 py-4 shrink-0">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Host Events</h3>
          <div className="flex items-center gap-2">
            <button
              onClick={exportToCSV}
              disabled={filteredEvents.length === 0}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-surface-1 hover:bg-surface-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="h-3.5 w-3.5" />
              <span>Export CSV</span>
            </button>
            <button
              onClick={toggleSortOrder}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-surface-1 hover:bg-surface-2 text-sm"
            >
              <ArrowUpDown className="h-3.5 w-3.5" />
              <span>{sortOrder === 'desc' ? 'Newest First' : 'Oldest First'}</span>
            </button>
            <button
              onClick={resetFilters}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-surface-1 hover:bg-surface-2 text-sm"
            >
              <X className="h-3.5 w-3.5" />
              <span>Reset</span>
            </button>
          </div>
        </div>

        {/* Filter Row */}
        <div className="grid grid-cols-5 gap-3">
          {/* Time Range */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">TIME RANGE</label>
            <select
              value={filters.hours}
              onChange={(e) => updateFilter('hours', Number(e.target.value))}
              className="w-full px-3 py-2 rounded-lg border border-border bg-surface-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            >
              {TIME_RANGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          {/* Severity */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">SEVERITY</label>
            <select
              value={filters.severity}
              onChange={(e) => updateFilter('severity', e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border bg-surface-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="">All Severity</option>
              {SEVERITY_OPTIONS.map((sev) => (
                <option key={sev} value={sev}>
                  {sev.charAt(0).toUpperCase() + sev.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {/* Category */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">CATEGORY</label>
            <select
              value={filters.category}
              onChange={(e) => updateFilter('category', e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border bg-surface-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="">All Categories</option>
              {CATEGORY_OPTIONS.map((cat) => (
                <option key={cat} value={cat}>
                  {cat.charAt(0).toUpperCase() + cat.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {/* Container Search with Checkboxes */}
          <div ref={containerDropdownRef} className="relative">
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">CONTAINER</label>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
              <input
                type="text"
                value={containerSearchInput}
                onChange={(e) => setContainerSearchInput(e.target.value)}
                onFocus={() => setShowContainerDropdown(true)}
                placeholder={selectedContainerIds.length > 0 ? `${selectedContainerIds.length} selected` : 'Search containers...'}
                className="w-full pl-9 pr-3 py-2 rounded-lg border border-border bg-surface-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            {/* Container Dropdown with Checkboxes */}
            {showContainerDropdown && (
              <div className="absolute z-50 w-full mt-1 py-1 rounded-lg border border-border bg-surface shadow-lg max-h-[300px] overflow-y-auto">
                {filteredContainers.length === 0 ? (
                  <div className="px-3 py-2 text-sm text-muted-foreground">No containers found</div>
                ) : (
                  filteredContainers.map((container) => {
                    const isSelected = selectedContainerIds.includes(container.id)
                    return (
                      <button
                        key={container.id}
                        onClick={() => toggleContainerSelection(container.id)}
                        className="w-full px-3 py-2 text-left text-sm flex items-center gap-2 hover:bg-surface-2 transition-colors"
                      >
                        <div
                          className={`h-4 w-4 rounded border flex items-center justify-center ${
                            isSelected
                              ? 'bg-primary border-primary'
                              : 'border-border bg-surface-1'
                          }`}
                        >
                          {isSelected && <Check className="h-3 w-3 text-primary-foreground" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="font-medium truncate">{container.name}</div>
                        </div>
                      </button>
                    )
                  })
                )}
              </div>
            )}
          </div>

          {/* Search */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1.5">SEARCH</label>
            <input
              type="text"
              value={filters.search}
              onChange={(e) => updateFilter('search', e.target.value)}
              placeholder="Search..."
              className="w-full px-3 py-2 rounded-lg border border-border bg-surface-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
        </div>
      </div>

      {/* Events Table */}
      {filteredEvents.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center py-8 text-muted-foreground">
            <Calendar className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p className="text-sm">No events found</p>
          </div>
        </div>
      ) : (
        <>
          {/* Table Header */}
          <div className="sticky top-0 bg-surface border-b border-border px-6 py-2 grid grid-cols-[200px_120px_1fr] gap-4 text-xs font-medium text-muted-foreground shrink-0">
            <div>TIMESTAMP</div>
            <div>SEVERITY</div>
            <div>EVENT DETAILS</div>
          </div>

          {/* Table Rows */}
          <div className="flex-1 overflow-y-auto divide-y divide-border">
            {filteredEvents.map((event) => (
              <EventRow key={event.id} event={event} showMetadata={true} compact={false} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
