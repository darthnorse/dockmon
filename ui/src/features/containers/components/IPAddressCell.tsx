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

  // Multiple networks - show each IP on a separate line
  // Show primary IP first, then the rest
  const allIps = Object.entries(docker_ips || {})
  const primaryEntry = allIps.find(([, ip]) => ip === docker_ip)
  const otherEntries = allIps.filter(([, ip]) => ip !== docker_ip)
  const sortedEntries = primaryEntry ? [primaryEntry, ...otherEntries] : allIps

  return (
    <div className="flex flex-col gap-0.5">
      {sortedEntries.map(([network, ip]) => (
        <span key={network} className="text-sm text-muted-foreground">
          {ip}
        </span>
      ))}
    </div>
  )
}
