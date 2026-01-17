/**
 * ContainerShellTab - Interactive shell for container
 *
 * Uses xterm.js for terminal emulation with WebSocket backend
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'
import { AlertCircle, Terminal as TerminalIcon, RotateCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface ContainerShellTabProps {
  hostId: string
  containerId: string
  containerName: string
  isRunning: boolean
}

export function ContainerShellTab({
  hostId,
  containerId,
  containerName,
  isRunning,
}: ContainerShellTabProps) {
  const terminalRef = useRef<HTMLDivElement>(null)
  const terminalInstance = useRef<Terminal | null>(null)
  const fitAddon = useRef<FitAddon | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const resizeObserverRef = useRef<ResizeObserver | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const hasConnectedOnce = useRef(false)

  // Connect to shell
  const connect = useCallback(() => {
    if (!terminalRef.current) return

    setError(null)

    // Initialize terminal
    const terminal = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
      theme: {
        background: '#0d0e12',
        foreground: '#e4e4e7',
        cursor: '#e4e4e7',
        selectionBackground: '#3b82f680',
        black: '#18181b',
        red: '#ef4444',
        green: '#22c55e',
        yellow: '#eab308',
        blue: '#3b82f6',
        magenta: '#a855f7',
        cyan: '#06b6d4',
        white: '#e4e4e7',
        brightBlack: '#71717a',
        brightRed: '#f87171',
        brightGreen: '#4ade80',
        brightYellow: '#facc15',
        brightBlue: '#60a5fa',
        brightMagenta: '#c084fc',
        brightCyan: '#22d3ee',
        brightWhite: '#fafafa',
      },
    })

    const fit = new FitAddon()
    terminal.loadAddon(fit)
    terminal.loadAddon(new WebLinksAddon())

    terminal.open(terminalRef.current)

    terminalInstance.current = terminal
    fitAddon.current = fit

    // Use ResizeObserver for proper size detection
    const resizeObserver = new ResizeObserver(() => {
      if (fitAddon.current && terminalInstance.current) {
        fitAddon.current.fit()
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          const dims = fitAddon.current.proposeDimensions()
          if (dims) {
            wsRef.current.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }))
          }
        }
      }
    })
    resizeObserver.observe(terminalRef.current)
    resizeObserverRef.current = resizeObserver

    // Initial fit after a short delay to ensure container has dimensions
    requestAnimationFrame(() => {
      fit.fit()

      // Construct WebSocket URL
      const basePath = import.meta.env.BASE_URL.replace(/\/$/, '')
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${wsProtocol}//${window.location.host}${basePath}/ws/shell/${hostId}/${containerId}`

      const ws = new WebSocket(wsUrl)
      ws.binaryType = 'arraybuffer'

      ws.onopen = () => {
        setIsConnected(true)
        fit.fit()
        const dims = fit.proposeDimensions()
        if (dims) {
          ws.send(JSON.stringify({ type: 'resize', cols: dims.cols, rows: dims.rows }))
        }
        terminal.focus()
      }

      ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          terminal.write(new Uint8Array(event.data))
        } else {
          terminal.write(event.data)
        }
      }

      ws.onerror = () => {
        setIsConnected(false)
        setError('Connection error')
      }

      ws.onclose = (event) => {
        setIsConnected(false)
        if (event.code !== 1000) {
          setError(event.reason || 'Connection closed')
        }
      }

      terminal.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(new TextEncoder().encode(data))
        }
      })

      // Note: Resize is handled by ResizeObserver above to avoid duplicate messages

      wsRef.current = ws
    })
  }, [hostId, containerId])

  // Cleanup resources
  const cleanup = useCallback(() => {
    if (resizeObserverRef.current) {
      resizeObserverRef.current.disconnect()
      resizeObserverRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    if (terminalInstance.current) {
      terminalInstance.current.dispose()
      terminalInstance.current = null
    }
  }, [])

  // Reset shell - disconnect and reconnect
  const resetShell = useCallback(() => {
    cleanup()
    setIsConnected(false)
    setError(null)
    // Small delay before reconnecting
    setTimeout(() => {
      connect()
    }, 100)
  }, [cleanup, connect])

  // Reset state and cleanup when container changes
  useEffect(() => {
    hasConnectedOnce.current = false
    return () => {
      cleanup()
    }
  }, [containerId, cleanup])

  // Cleanup when container stops running
  useEffect(() => {
    if (!isRunning) {
      cleanup()
      setIsConnected(false)
      setError(null)
    }
  }, [isRunning, cleanup])

  // Auto-connect on mount (only once per container)
  useEffect(() => {
    if (isRunning && !hasConnectedOnce.current) {
      hasConnectedOnce.current = true
      const timer = setTimeout(() => {
        connect()
      }, 100)
      return () => clearTimeout(timer)
    }
    return undefined
  }, [isRunning, connect])

  // Show error if container not running
  if (!isRunning) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-4">
          <AlertCircle className="h-12 w-12 text-warning mx-auto" />
          <div>
            <h3 className="font-medium">Container Not Running</h3>
            <p className="text-sm text-muted-foreground mt-1">
              Start the container to access its shell.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <TerminalIcon className="h-4 w-4" />
          <span className="text-sm font-medium">{containerName}</span>
          {isConnected && (
            <span className="text-xs px-2 py-0.5 rounded bg-success/20 text-success">
              connected
            </span>
          )}
        </div>
        <div className="relative group">
          <Button size="sm" variant="ghost" onClick={resetShell}>
            <RotateCw className="h-4 w-4" />
          </Button>
          <span className="absolute right-0 top-full mt-1 px-2 py-1 text-xs bg-surface-1 border border-border rounded shadow-lg opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
            Reset shell session
          </span>
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="px-4 py-2 bg-danger/10 border-b border-danger/20 shrink-0">
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}

      {/* Terminal container */}
      <div className="flex-1 relative min-h-0 overflow-hidden" style={{ backgroundColor: '#0d0e12' }}>
        {/* Padding wrapper - xterm measures the inner div */}
        <div className="absolute inset-0 p-3">
          <div ref={terminalRef} className="h-full w-full" />
        </div>
      </div>
    </div>
  )
}
