/**
 * EventsPage Component
 *
 * Comprehensive event log viewer with filtering
 */

import { useState, useMemo } from 'react'
import { useEvents } from '@/hooks/useEvents'
import { useHosts } from '@/features/hosts/hooks/useHosts'
import type { EventFilters, EventSeverity, EventCategory } from '@/types/events'
import { formatSeverity, getSeverityColor, formatRelativeTime, formatTimestamp } from '@/lib/utils/eventUtils'
import { Calendar, Filter, Search, X, Server } from 'lucide-react'
import { HostMultiSelect } from './components/HostMultiSelect'

const SEVERITY_OPTIONS: EventSeverity[] = ['critical', 'error', 'warning', 'info', 'debug']
const CATEGORY_OPTIONS: EventCategory[] = ['container', 'host', 'system', 'alert', 'notification', 'user']

export function EventsPage() {
  const [filters, setFilters] = useState<EventFilters>({
    limit: 100,
    offset: 0,
    hours: 24, // Default to last 24 hours
  })
  const [searchInput, setSearchInput] = useState('')
  const [showFilters, setShowFilters] = useState(false)

  // Fetch hosts for the multi-select dropdown
  const { data: hosts = [] } = useHosts()

  // Fetch events
  const { data: eventsData, isLoading, error } = useEvents(filters, {
    refetchInterval: 30000, // Refresh every 30 seconds
  })

  const events = eventsData?.events ?? []
  const totalCount = eventsData?.total_count ?? 0
  const hasMore = eventsData?.has_more ?? false

  // Handle filter changes
  const updateFilter = <K extends keyof EventFilters>(key: K, value: EventFilters[K]) => {
    setFilters((prev) => ({
      ...prev,
      [key]: value,
      offset: 0, // Reset pagination when filters change
    }))
  }

  const toggleSeverity = (severity: EventSeverity) => {
    const current = filters.severity ?? []
    const updated = current.includes(severity)
      ? current.filter((s) => s !== severity)
      : [...current, severity]
    updateFilter('severity', updated.length > 0 ? updated : undefined)
  }

  const toggleCategory = (category: EventCategory) => {
    const current = filters.category ?? []
    const updated = current.includes(category)
      ? current.filter((c) => c !== category)
      : [...current, category]
    updateFilter('category', updated.length > 0 ? updated : undefined)
  }

  const handleSearch = () => {
    updateFilter('search', searchInput || undefined)
  }

  const clearFilters = () => {
    setFilters({ limit: 100, offset: 0, hours: 24 })
    setSearchInput('')
  }

  const activeFilterCount = useMemo(() => {
    let count = 0
    if (filters.severity && filters.severity.length > 0) count++
    if (filters.category && filters.category.length > 0) count++
    if (filters.host_id && filters.host_id.length > 0) count++
    if (filters.search) count++
    if (filters.hours !== 24) count++
    return count
  }, [filters])

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="border-b border-border bg-surface p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <Calendar className="h-6 w-6 text-primary" />
            <h1 className="text-2xl font-semibold">Events</h1>
          </div>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border hover:bg-surface-2 transition-colors"
          >
            <Filter className="h-4 w-4" />
            <span>Filters</span>
            {activeFilterCount > 0 && (
              <span className="px-2 py-0.5 rounded-full bg-primary text-primary-foreground text-xs font-medium">
                {activeFilterCount}
              </span>
            )}
          </button>
        </div>

        {/* Search Bar */}
        <div className="flex gap-3">
          <div className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Search events..."
              className="w-full pl-10 pr-4 py-2 rounded-lg border border-border bg-surface-1 focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>
          <button
            onClick={handleSearch}
            className="px-6 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors font-medium"
          >
            Search
          </button>
        </div>

        {/* Filters Panel */}
        {showFilters && (
          <div className="mt-4 p-4 rounded-lg border border-border bg-surface-1 space-y-4">
            {/* Host Multi-Select */}
            <div>
              <label className="block text-sm font-medium mb-2">Hosts</label>
              <HostMultiSelect
                hosts={hosts}
                selectedHostIds={filters.host_id ?? []}
                onChange={(hostIds) => updateFilter('host_id', hostIds.length > 0 ? hostIds : undefined)}
                placeholder="Filter by hosts..."
              />
            </div>

            {/* Severity Filter */}
            <div>
              <label className="block text-sm font-medium mb-2">Severity</label>
              <div className="flex flex-wrap gap-2">
                {SEVERITY_OPTIONS.map((severity) => {
                  const isActive = filters.severity?.includes(severity)
                  const colors = getSeverityColor(severity)
                  return (
                    <button
                      key={severity}
                      onClick={() => toggleSeverity(severity)}
                      className={`px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${
                        isActive
                          ? `${colors.bg} ${colors.text} ${colors.border}`
                          : 'border-border bg-surface hover:bg-surface-2'
                      }`}
                    >
                      {formatSeverity(severity)}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Category Filter */}
            <div>
              <label className="block text-sm font-medium mb-2">Category</label>
              <div className="flex flex-wrap gap-2">
                {CATEGORY_OPTIONS.map((category) => {
                  const isActive = filters.category?.includes(category)
                  return (
                    <button
                      key={category}
                      onClick={() => toggleCategory(category)}
                      className={`px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors capitalize ${
                        isActive
                          ? 'bg-primary/20 text-primary border-primary/30'
                          : 'border-border bg-surface hover:bg-surface-2'
                      }`}
                    >
                      {category}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Time Range */}
            <div>
              <label className="block text-sm font-medium mb-2">Time Range</label>
              <div className="flex gap-2">
                {[1, 6, 12, 24, 48, 168].map((hours) => {
                  const isActive = filters.hours === hours
                  const label = hours < 24 ? `${hours}h` : `${hours / 24}d`
                  return (
                    <button
                      key={hours}
                      onClick={() => updateFilter('hours', hours)}
                      className={`px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${
                        isActive
                          ? 'bg-primary text-primary-foreground border-primary'
                          : 'border-border bg-surface hover:bg-surface-2'
                      }`}
                    >
                      {label}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Clear Filters */}
            {activeFilterCount > 0 && (
              <div className="pt-2 border-t border-border">
                <button
                  onClick={clearFilters}
                  className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  <X className="h-4 w-4" />
                  Clear all filters
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Events List */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-muted-foreground">Loading events...</div>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-red-500">Error loading events: {error.message}</div>
          </div>
        ) : events.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-center">
            <Calendar className="h-16 w-16 text-muted-foreground/50 mb-4" />
            <p className="text-lg font-medium">No events found</p>
            <p className="text-sm text-muted-foreground mt-1">
              Try adjusting your filters or time range
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {/* Results Info */}
            <div className="flex items-center justify-between text-sm text-muted-foreground pb-2">
              <span>
                Showing {events.length} of {totalCount} events
              </span>
              {hasMore && (
                <button
                  onClick={() => updateFilter('limit', (filters.limit ?? 100) + 100)}
                  className="text-primary hover:underline"
                >
                  Load more
                </button>
              )}
            </div>

            {/* Event Cards */}
            {events.map((event) => {
              const severityColors = getSeverityColor(event.severity)
              return (
                <div
                  key={event.id}
                  className="p-4 rounded-lg border border-border bg-surface hover:bg-surface-2 transition-colors"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      {/* Header */}
                      <div className="flex items-center gap-2 mb-2">
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-medium border ${severityColors.bg} ${severityColors.text} ${severityColors.border}`}
                        >
                          {formatSeverity(event.severity)}
                        </span>
                        <span className="text-xs text-muted-foreground capitalize">
                          {event.category}
                        </span>
                        {event.host_name && (
                          <span className="flex items-center gap-1 text-xs text-muted-foreground">
                            <Server className="h-3 w-3" />
                            {event.host_name}
                          </span>
                        )}
                        <span className="text-xs text-muted-foreground ml-auto" title={formatTimestamp(event.timestamp)}>
                          {formatRelativeTime(event.timestamp)}
                        </span>
                      </div>

                      {/* Title */}
                      <h3 className="font-medium mb-1">{event.title}</h3>

                      {/* Message */}
                      {event.message && (
                        <p className="text-sm text-muted-foreground line-clamp-2">{event.message}</p>
                      )}

                      {/* Container/State Info */}
                      <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
                        {event.container_name && (
                          <span>Container: {event.container_name}</span>
                        )}
                        {event.old_state && event.new_state && (
                          <span>
                            {event.old_state} → {event.new_state}
                          </span>
                        )}
                        {event.triggered_by && (
                          <span>By: {event.triggered_by}</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
