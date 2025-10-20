/**
 * LogViewer - Reusable container log viewer component
 *
 * Features:
 * - Real-time log streaming (polls every 2 seconds)
 * - Multi-container support with color coding
 * - Search/filter with regex support
 * - Timestamps toggle
 * - Auto-scroll with manual scroll detection
 * - Sort order (newest/oldest first)
 * - Download logs
 * - Clear logs
 * - Tail count selector
 */

import { useState, useEffect, useRef } from 'react'
import {
  Search,
  Download,
  Trash2,
  Clock,
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
} from 'lucide-react'
import { apiClient } from '@/lib/api/client'
import { debug } from '@/lib/debug'
import { toast } from 'sonner'

interface LogLine {
  timestamp: string
  log: string
  containerName?: string
  containerKey?: string
}

interface ContainerSelection {
  hostId: string
  containerId: string
  name: string
}

interface LogViewerProps {
  /** Container selections to stream logs from (max 15) */
  containers: ContainerSelection[]
  /** Show container names when streaming multiple containers */
  showContainerNames?: boolean
  /** Height of log container */
  height?: string
  /** Auto-refresh enabled by default */
  autoRefreshDefault?: boolean
  /** Show controls (search, download, etc.) */
  showControls?: boolean
  /** Compact mode (smaller padding, fonts) */
  compact?: boolean
}

// Container colors (8 distinct colors for color coding)
const CONTAINER_COLORS = [
  'text-blue-400',
  'text-green-400',
  'text-yellow-400',
  'text-purple-400',
  'text-pink-400',
  'text-cyan-400',
  'text-orange-400',
  'text-lime-400',
]

export function LogViewer({
  containers,
  showContainerNames = true,
  height = '400px',
  autoRefreshDefault = true,
  showControls = true,
  compact = false,
}: LogViewerProps) {
  const [logs, setLogs] = useState<LogLine[]>([])
  const [filteredLogs, setFilteredLogs] = useState<LogLine[]>([])
  const [searchTerm, setSearchTerm] = useState('')
  const [showTimestamps, setShowTimestamps] = useState(true)
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [autoRefresh, setAutoRefresh] = useState(autoRefreshDefault)
  const [tailCount, setTailCount] = useState<number | 'all'>(100)
  const [userHasScrolled, setUserHasScrolled] = useState(false)

  const logContainerRef = useRef<HTMLDivElement>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)
  const containerColorMap = useRef<Record<string, number>>({})
  const nextColorIndex = useRef(0)
  const isFetchingRef = useRef(false)

  // Use refs for values that change but shouldn't trigger fetchLogs recreation
  const tailCountRef = useRef(tailCount)
  const sortOrderRef = useRef(sortOrder)
  const userHasScrolledRef = useRef(userHasScrolled)

  // Keep refs in sync
  useEffect(() => { tailCountRef.current = tailCount }, [tailCount])
  useEffect(() => { sortOrderRef.current = sortOrder }, [sortOrder])
  useEffect(() => { userHasScrolledRef.current = userHasScrolled }, [userHasScrolled])

  // Assign colors to containers
  useEffect(() => {
    containers.forEach((container) => {
      const key = `${container.hostId}:${container.containerId}`
      if (!(key in containerColorMap.current)) {
        containerColorMap.current[key] = nextColorIndex.current % CONTAINER_COLORS.length
        nextColorIndex.current++
      }
    })
  }, [containers])

  // Scroll to bottom
  const scrollToBottom = () => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }

  // Scroll to top
  const scrollToTop = () => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = 0
    }
  }

  // Fetch logs from all selected containers
  const fetchLogs = async () => {
    if (containers.length === 0) return
    if (isFetchingRef.current) {
      debug.log('LogViewer', 'Fetch already in progress, skipping')
      return
    }

    isFetchingRef.current = true
    const tail = tailCountRef.current === 'all' ? 10000 : tailCountRef.current
    let rateLimitHit = false

    try {
      // Fetch logs from all containers with staggered delays
      const promises = containers.map(async (container, index) => {
        // Add 100ms delay between requests to avoid rate limiting
        if (index > 0) {
          await new Promise((resolve) => setTimeout(resolve, index * 100))
        }

        try {
          const response = await apiClient.get<{ logs: LogLine[] }>(
            `/hosts/${container.hostId}/containers/${container.containerId}/logs`,
            { params: { tail } }
          )

          // Add container info to each log line
          return (response.logs || []).map((log) => ({
            ...log,
            containerName: container.name,
            containerKey: `${container.hostId}:${container.containerId}`,
          }))
        } catch (error: any) {
          if (error?.response?.status === 429) {
            rateLimitHit = true
          }
          return []
        }
      })

      const logsArrays = await Promise.all(promises)

      if (rateLimitHit) {
        setAutoRefresh(false)
        toast.error('Rate limit reached. Auto-refresh disabled.')
      }

      // Merge and sort logs
      const newLogs = logsArrays.flat()
      newLogs.sort((a, b) => {
        const aTime = new Date(a.timestamp).getTime()
        const bTime = new Date(b.timestamp).getTime()
        return sortOrderRef.current === 'asc' ? aTime - bTime : bTime - aTime
      })

      // Only auto-scroll if user hasn't manually scrolled away
      const shouldAutoScroll = !userHasScrolledRef.current
      setLogs(newLogs)

      if (shouldAutoScroll) {
        setTimeout(() => {
          if (sortOrderRef.current === 'desc') {
            // Desc = newest first, so new logs appear at top
            scrollToTop()
          } else {
            // Asc = oldest first, so new logs appear at bottom
            scrollToBottom()
          }
        }, 0)
      }
    } catch (error) {
      debug.error('LogViewer', 'Error fetching logs:', error)
    } finally {
      isFetchingRef.current = false
    }
  }

  // Filter logs based on search term
  useEffect(() => {
    if (!searchTerm.trim()) {
      setFilteredLogs(logs)
      return
    }

    try {
      // Try regex search first
      const regex = new RegExp(searchTerm, 'i')
      setFilteredLogs(logs.filter((log) => regex.test(log.log)))
    } catch {
      // Fallback to plain string search
      const searchLower = searchTerm.toLowerCase()
      setFilteredLogs(logs.filter((log) => log.log.toLowerCase().includes(searchLower)))
    }
  }, [logs, searchTerm])

  // Track container IDs to detect actual changes (not just reference changes)
  const containerIdsRef = useRef<string>('')
  const prevContainerIds = containerIdsRef.current
  const currentContainerIds = containers.map(c => `${c.hostId}:${c.containerId}`).sort().join(',')
  const containersChanged = prevContainerIds !== currentContainerIds

  // Update container IDs ref
  useEffect(() => {
    containerIdsRef.current = currentContainerIds
  }, [currentContainerIds])

  // Initial fetch when containers actually change (not just reference change)
  useEffect(() => {
    if (containersChanged && containers.length > 0) {
      setLogs([])
      fetchLogs()
    }
  }, [containersChanged, containers.length])

  // Auto-refresh polling - only when autoRefresh is enabled
  useEffect(() => {
    // Clear any existing interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }

    // Start polling if conditions are met
    if (autoRefresh && containers.length > 0) {
      intervalRef.current = setInterval(fetchLogs, 2000) // Poll every 2 seconds
    }

    // Cleanup on unmount or when dependencies change
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [autoRefresh, containers.length])

  // Re-sort when sort order changes
  useEffect(() => {
    setLogs((prev) => {
      const sorted = [...prev]
      sorted.sort((a, b) => {
        const aTime = new Date(a.timestamp).getTime()
        const bTime = new Date(b.timestamp).getTime()
        return sortOrder === 'asc' ? aTime - bTime : bTime - aTime
      })
      return sorted
    })
  }, [sortOrder])

  const handleDownload = () => {
    if (filteredLogs.length === 0) return

    let content = ''
    filteredLogs.forEach((log) => {
      let line = ''
      if (showTimestamps) {
        line += `[${new Date(log.timestamp).toISOString()}] `
      }
      if (showContainerNames && log.containerName) {
        line += `[${log.containerName}] `
      }
      line += log.log + '\n'
      content += line
    })

    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `container-logs-${new Date().toISOString()}.txt`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleClear = () => {
    setLogs([])
    setFilteredLogs([])
  }

  const handleToggleSort = () => {
    setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
  }

  // Detect when user manually scrolls
  useEffect(() => {
    const container = logContainerRef.current
    if (!container) return

    const handleScroll = () => {
      const { scrollHeight, scrollTop, clientHeight } = container

      // Check if user scrolled away from the auto-scroll position
      if (sortOrder === 'desc') {
        // In desc mode, newest logs are at top, so auto-scroll is to top
        const atTop = scrollTop <= 100
        setUserHasScrolled(!atTop)
      } else {
        // In asc mode, newest logs are at bottom, so auto-scroll is to bottom
        const atBottom = scrollHeight - scrollTop <= clientHeight + 100
        setUserHasScrolled(!atBottom)
      }
    }

    container.addEventListener('scroll', handleScroll)
    return () => container.removeEventListener('scroll', handleScroll)
  }, [sortOrder])

  // Reset userHasScrolled when auto-refresh is toggled
  useEffect(() => {
    setUserHasScrolled(false)
  }, [autoRefresh])

  // Reset userHasScrolled when containers change
  useEffect(() => {
    setUserHasScrolled(false)
  }, [containers])

  const getContainerColor = (containerKey: string | undefined) => {
    if (!containerKey) return ''
    const colorIndex = containerColorMap.current[containerKey] || 0
    return CONTAINER_COLORS[colorIndex]
  }

  return (
    <div className="flex flex-col h-full">
      {/* Controls */}
      {showControls && (
        <div className={`flex flex-wrap items-center gap-2 border-b border-border ${compact ? 'p-2' : 'p-3'}`}>
          {/* Search */}
          <div className="flex-1 min-w-[200px]">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Search logs (regex supported)..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className={`w-full pl-8 pr-3 border border-border rounded bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary ${
                  compact ? 'py-1 text-xs' : 'py-1.5 text-sm'
                }`}
              />
            </div>
          </div>

          {/* Tail Count */}
          <select
            value={tailCount}
            onChange={(e) => setTailCount(e.target.value === 'all' ? 'all' : Number(e.target.value))}
            className={`border border-border rounded bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary ${
              compact ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm'
            }`}
          >
            <option value={50}>50 lines</option>
            <option value={100}>100 lines</option>
            <option value={500}>500 lines</option>
            <option value={1000}>1000 lines</option>
            <option value="all">All lines</option>
          </select>

          {/* Timestamps Toggle */}
          <button
            onClick={() => setShowTimestamps(!showTimestamps)}
            className={`flex items-center gap-1.5 px-3 border border-border rounded transition-colors ${
              showTimestamps
                ? 'bg-primary text-primary-foreground'
                : 'bg-background text-foreground hover:bg-muted'
            } ${compact ? 'py-1 text-xs' : 'py-1.5 text-sm'}`}
            title="Toggle timestamps"
          >
            <Clock className="w-3.5 h-3.5" />
            {!compact && 'Time'}
          </button>

          {/* Sort Toggle */}
          <button
            onClick={handleToggleSort}
            className={`flex items-center gap-1.5 px-3 border border-border rounded bg-background text-foreground hover:bg-muted transition-colors ${
              compact ? 'py-1 text-xs' : 'py-1.5 text-sm'
            }`}
            title={sortOrder === 'desc' ? 'Newest first' : 'Oldest first'}
          >
            {sortOrder === 'desc' ? (
              <ArrowDownWideNarrow className="w-3.5 h-3.5" />
            ) : (
              <ArrowUpNarrowWide className="w-3.5 h-3.5" />
            )}
            {!compact && (sortOrder === 'desc' ? 'Newest' : 'Oldest')}
          </button>

          {/* Auto-refresh Toggle */}
          <label className={`flex items-center gap-2 cursor-pointer ${compact ? 'text-xs' : 'text-sm'}`}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-border"
            />
            <span className="text-foreground">{compact ? 'Auto' : 'Auto-refresh'}</span>
          </label>

          {/* Clear */}
          <button
            onClick={handleClear}
            disabled={logs.length === 0}
            className={`p-2 text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed transition-colors ${
              compact ? 'text-xs' : 'text-sm'
            }`}
            title="Clear logs"
          >
            <Trash2 className="w-4 h-4" />
          </button>

          {/* Download */}
          <button
            onClick={handleDownload}
            disabled={filteredLogs.length === 0}
            className={`p-2 text-muted-foreground hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed transition-colors ${
              compact ? 'text-xs' : 'text-sm'
            }`}
            title="Download logs"
          >
            <Download className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Log Container */}
      <div
        ref={logContainerRef}
        className={`flex-1 overflow-y-auto bg-card font-mono ${compact ? 'text-xs' : 'text-sm'}`}
        style={{ height }}
        data-testid="logs-content"
      >
        {filteredLogs.length === 0 ? (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            {containers.length === 0
              ? 'Select containers to view logs'
              : logs.length === 0
              ? 'No logs available'
              : 'No logs match search term'}
          </div>
        ) : (
          <div className={compact ? 'p-2' : 'p-3'}>
            {filteredLogs.map((log, index) => (
              <div key={`${log.timestamp}-${index}`} className="leading-relaxed py-0.5">
                {showTimestamps && (
                  <span className="text-muted-foreground mr-2">
                    {new Date(log.timestamp).toLocaleString('en-US', {
                      month: '2-digit',
                      day: '2-digit',
                      year: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                      hour12: true,
                    })}
                  </span>
                )}
                {showContainerNames && log.containerName && containers.length > 1 && (
                  <span className={`font-semibold mr-2 ${getContainerColor(log.containerKey)}`}>
                    [{log.containerName}]
                  </span>
                )}
                <span className="text-foreground">{log.log}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
