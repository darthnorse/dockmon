/**
 * IP Address Cell Component
 * Displays container Docker network IP addresses with tooltip for multiple networks
 * GitHub Issue #37
 */

import type { Container } from '../types'

interface IPAddressCellProps {
  container: Container
}

export function IPAddressCell({ container }: IPAddressCellProps) {
  const { docker_ip, docker_ips } = container

  // No IP address
  if (!docker_ip) {
    return <span className="text-sm text-muted-foreground">Not connected</span>
  }

  const networkCount = docker_ips ? Object.keys(docker_ips).length : 1
  const hasMultipleNetworks = networkCount > 1

  // Single network - just display IP
  if (!hasMultipleNetworks) {
    return <span className="text-sm text-muted-foreground">{docker_ip}</span>
  }

  // Multiple networks - show primary + count with tooltip
  const tooltipText = Object.entries(docker_ips || {})
    .map(([network, ip]) => `${network}: ${ip}`)
    .join('\n')

  return (
    <div className="flex items-center gap-1.5 cursor-help" title={tooltipText}>
      <span className="text-sm text-muted-foreground">{docker_ip}</span>
      <span className="text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded-md">
        +{networkCount - 1}
      </span>
    </div>
  )
}
