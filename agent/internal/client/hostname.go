package client

// selectHostname picks the registration hostname using a fixed precedence chain.
//
// Precedence (highest first):
//  1. agentName    — operator-supplied AGENT_NAME env var (lets cloned VMs / hosts
//                    with shared OS hostnames be distinguished in the DockMon UI).
//  2. systemHost   — Docker daemon's reported hostname (typically the host's OS
//                    hostname, even when the agent runs in a container).
//  3. osHost       — os.Hostname() result (the agent process's own hostname; will
//                    be the container ID when the agent runs in Docker).
//  4. engineID     — last-resort identifier; truncated to at most 12 chars
//                    (returned as-is if shorter) per DockMon's short-ID convention.
//
// Returns "" only when every input is empty, which the caller is expected to
// treat as a registration error upstream.
func selectHostname(agentName, systemHost, osHost, engineID string) string {
	if agentName != "" {
		return agentName
	}
	if systemHost != "" {
		return systemHost
	}
	if osHost != "" {
		return osHost
	}
	if len(engineID) > 12 {
		return engineID[:12]
	}
	return engineID
}
