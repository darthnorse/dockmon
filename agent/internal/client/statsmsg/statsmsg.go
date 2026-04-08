// Package statsmsg defines the wire format for agent → stats-service stats
// ingestion. It lives in its own package so both the agent's `client` package
// (which owns the WebSocket transport) and the agent's `handlers` package
// (which produces stats samples) can reference the type without importing
// each other — `client` already imports `handlers` for the main agent
// WebSocket client, so a direct reverse import would create a cycle.
package statsmsg

// AgentStatsMsg is the wire format for stats-service ingestion.
// Deliberately does NOT include a host_id field — the stats-service
// binds host_id from the agent token at upgrade time, so a compromised
// agent cannot spoof its host identity.
type AgentStatsMsg struct {
	ContainerID   string  `json:"container_id"`
	ContainerName string  `json:"container_name"`
	CPUPercent    float64 `json:"cpu_percent"`
	MemoryUsage   uint64  `json:"memory_usage"`
	MemoryLimit   uint64  `json:"memory_limit"`
	MemoryPercent float64 `json:"memory_percent"`
	NetworkRx     uint64  `json:"network_rx"`
	NetworkTx     uint64  `json:"network_tx"`
	DiskRead      uint64  `json:"disk_read"`
	DiskWrite     uint64  `json:"disk_write"`
	Timestamp     string  `json:"timestamp"`
}
