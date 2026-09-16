package client

import "github.com/darthnorse/dockmon-agent/internal/docker"

// systemInfoPayload is the host-facts shape the backend applies to its
// DockerHostDB row, shared by registration and the get_system_info command.
func systemInfoPayload(info *docker.SystemInfo) map[string]interface{} {
	return map[string]interface{}{
		"os_type":           info.OSType,
		"os_version":        info.OSVersion,
		"kernel_version":    info.KernelVersion,
		"docker_version":    info.DockerVersion,
		"daemon_started_at": info.DaemonStartedAt,
		"total_memory":      info.TotalMemory,
		"num_cpus":          info.NumCPUs,
	}
}
