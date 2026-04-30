package client

// selectHostname picks the registration hostname using a fixed precedence chain
// and returns both the chosen hostname and a short string indicating which
// tier it came from ("agent_name", "daemon", "os", or "engine_id").
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
// Returns ("", "engine_id") when every input is empty, which the caller is
// expected to treat as a registration error upstream. The source string is
// always non-empty so backend logs can record the audit trail unconditionally.
func selectHostname(agentName, systemHost, osHost, engineID string) (string, string) {
	if agentName != "" {
		return agentName, "agent_name"
	}
	if systemHost != "" {
		return systemHost, "daemon"
	}
	if osHost != "" {
		return osHost, "os"
	}
	if len(engineID) > 12 {
		return engineID[:12], "engine_id"
	}
	return engineID, "engine_id"
}
