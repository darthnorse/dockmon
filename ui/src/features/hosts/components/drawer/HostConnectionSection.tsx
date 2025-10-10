/**
 * HostConnectionSection Component
 *
 * Displays connection details: status, type (TCP/TLS/mTLS), last connection
 */

import { Shield, CheckCircle2, XCircle, AlertCircle } from 'lucide-react'
import { DrawerSection } from '@/components/ui/drawer'
import { formatDistanceToNow } from 'date-fns'

interface Host {
  id: string
  url: string
  status: 'online' | 'offline' | 'degraded'
  security_status?: string | null  // "secure", "insecure", "unknown"
  last_checked: string
}

interface HostConnectionSectionProps {
  host: Host
}

export function HostConnectionSection({ host }: HostConnectionSectionProps) {
  // Parse URL to get protocol and port
  const parsedUrl = new URL(host.url)
  const protocol = parsedUrl.protocol.replace(':', '')
  const port = parsedUrl.port || (protocol === 'https' ? '443' : protocol === 'http' ? '80' : '2375')

  // Determine if TLS is used based on URL and security_status
  const useTls = protocol === 'https' || host.security_status === 'secure'

  // Determine connection type
  const getConnectionType = () => {
    if (!useTls) return 'TCP (Unencrypted)'
    // We can't determine mTLS vs TLS from current data
    return 'TLS (Encrypted)'
  }

  const getSecurityIcon = () => {
    if (!useTls) return <Shield className="h-4 w-4 text-amber-500" />
    return <Shield className="h-4 w-4 text-green-500" />
  }

  const getStatusIcon = () => {
    switch (host.status) {
      case 'online':
        return <CheckCircle2 className="h-5 w-5 text-green-500" />
      case 'offline':
        return <XCircle className="h-5 w-5 text-red-500" />
      case 'degraded':
        return <AlertCircle className="h-5 w-5 text-yellow-500" />
    }
  }

  const getStatusText = () => {
    switch (host.status) {
      case 'online':
        return 'Connected'
      case 'offline':
        return 'Disconnected'
      case 'degraded':
        return 'Connection Issues'
    }
  }

  return (
    <DrawerSection title="Connection">
      <div className="space-y-4">
        {/* Connection Status */}
        <div className="flex items-center gap-3 p-3 rounded-lg bg-muted">
          {getStatusIcon()}
          <div className="flex-1">
            <p className="text-sm font-medium">{getStatusText()}</p>
            {host.last_checked && host.status === 'online' && (
              <p className="text-xs text-muted-foreground mt-0.5">
                Last checked {formatDistanceToNow(new Date(host.last_checked), { addSuffix: true })}
              </p>
            )}
          </div>
        </div>

        {/* Connection Details */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground">Protocol</label>
            <p className="text-sm mt-1">Docker API</p>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Port</label>
            <p className="text-sm mt-1 font-mono">{port}</p>
          </div>
        </div>

        {/* Security */}
        <div>
          <label className="text-xs font-medium text-muted-foreground flex items-center gap-2">
            Security
          </label>
          <div className="flex items-center gap-2 mt-2 p-3 rounded-lg bg-muted">
            {getSecurityIcon()}
            <span className="text-sm">{getConnectionType()}</span>
          </div>
        </div>


        {/* Warning for unencrypted */}
        {!useTls && (
          <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
            <AlertCircle className="h-4 w-4 text-amber-500 mt-0.5" />
            <div className="flex-1">
              <p className="text-sm font-medium text-amber-500">Unencrypted Connection</p>
              <p className="text-xs text-amber-500/80 mt-1">
                Docker API traffic is not encrypted. Enable TLS for production use.
              </p>
            </div>
          </div>
        )}
      </div>
    </DrawerSection>
  )
}
