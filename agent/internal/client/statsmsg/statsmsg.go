// Package statsmsg defines the wire format for agent → stats-service stats
// ingestion. It lives in its own package so both the agent's `client` package
// (which owns the WebSocket transport) and the agent's `handlers` package
// (which produces stats samples) can reference the type without importing
// each other — `client` already imports `handlers` for the main agent
// WebSocket client, so a direct reverse import would create a cycle.
package statsmsg

// Message types carried in AgentStatsMsg.Type. A stats-service predating the
// typed format ignores the field and drops host samples on their empty
// container_id, so adding it is backward-compatible in both directions.
const (
	TypeContainerStats = "container_stats"
	TypeHostStats      = "host_stats"
)

// AgentStatsMsg is the wire format for stats-service ingestion.
// Deliberately does NOT include a host_id field — the stats-service
// binds host_id from the agent token at upgrade time, so a compromised
// agent cannot spoof its host identity.
type AgentStatsMsg struct {
	Type          string  `json:"type"`
	ContainerID   string  `json:"container_id,omitempty"`
	ContainerName string  `json:"container_name,omitempty"`
	CPUPercent    float64 `json:"cpu_percent"`
	MemoryUsage   uint64  `json:"memory_usage,omitempty"`
	MemoryLimit   uint64  `json:"memory_limit,omitempty"`
	MemoryPercent float64 `json:"memory_percent"`
	NetworkRx     uint64  `json:"network_rx,omitempty"`
	NetworkTx     uint64  `json:"network_tx,omitempty"`
	DiskRead      uint64  `json:"disk_read,omitempty"`
	DiskWrite     uint64  `json:"disk_write,omitempty"`
	Timestamp     string  `json:"timestamp"`

	// Host-stats fields (Type == TypeHostStats): the agent's real /proc
	// readings. memory_percent is the field the alert evaluator reads — the
	// control WebSocket's mem_percent is a different, UI-only wire.
	MemoryUsedBytes  uint64 `json:"memory_used_bytes,omitempty"`
	MemoryLimitBytes uint64 `json:"memory_limit_bytes,omitempty"`

	*HostDisk
}

// HostDisk is the host filesystem reading on a host-stats sample. It is
// embedded as a pointer so a host that cannot measure disk sends none of the
// keys: a plain float64 would marshal 0% and read as an empty disk, while a
// genuine 0% still serializes. The five fields travel together or not at all.
type HostDisk struct {
	DiskPercent        float64 `json:"disk_percent"`
	DiskUsedBytes      uint64  `json:"disk_used_bytes"`
	DiskAvailableBytes uint64  `json:"disk_available_bytes"`
	DiskTotalBytes     uint64  `json:"disk_total_bytes"`
	// DiskSource is the logical host path measured (Docker's data-root, or
	// "/" when that fell back), so an operator can tell which disk it is.
	DiskSource string `json:"disk_source"`
}
