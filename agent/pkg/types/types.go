package types

import "time"

// Agent represents the agent's identity and capabilities
type Agent struct {
	ID            string            `json:"id"`
	HostID        string            `json:"host_id"`
	Token         string            `json:"token"`
	EngineID      string            `json:"engine_id"`
	Version       string            `json:"version"`
	ProtoVersion  string            `json:"proto_version"`
	Capabilities  map[string]bool   `json:"capabilities"`
	LastHeartbeat time.Time         `json:"last_heartbeat"`
}

// Message represents the WebSocket message envelope
type Message struct {
	Type          string            `json:"type"` // "command", "response", "event"
	ID            string            `json:"id,omitempty"` // Correlation ID
	Command       string            `json:"command,omitempty"`
	Payload       interface{}       `json:"payload,omitempty"`
	Error         string            `json:"error,omitempty"`
	Timestamp     time.Time         `json:"timestamp"`
}

// RegistrationRequest is sent by agent during initial connection
type RegistrationRequest struct {
	Token          string          `json:"token"`
	EngineID       string          `json:"engine_id"`
	Hostname       string          `json:"hostname,omitempty"`        // System hostname
	Version        string          `json:"version"`
	ProtoVersion   string          `json:"proto_version"`
	Capabilities   map[string]bool `json:"capabilities"`
	// System information (v2.2.0+)
	OSType         string `json:"os_type,omitempty"`          // "linux", "windows", etc.
	OSVersion      string `json:"os_version,omitempty"`       // e.g., "Ubuntu 22.04.3 LTS"
	KernelVersion  string `json:"kernel_version,omitempty"`   // e.g., "5.15.0-88-generic"
	DockerVersion  string `json:"docker_version,omitempty"`   // e.g., "24.0.6"
	DaemonStartedAt string `json:"daemon_started_at,omitempty"` // ISO timestamp when Docker daemon started
	TotalMemory    int64  `json:"total_memory,omitempty"`     // Total memory in bytes
	NumCPUs        int    `json:"num_cpus,omitempty"`         // Number of CPUs
}

// RegistrationResponse is returned by DockMon after successful registration
type RegistrationResponse struct {
	AgentID      string `json:"agent_id"`
	HostID       string `json:"host_id"`
	PermanentToken string `json:"permanent_token,omitempty"` // Only for first registration
}

// ContainerOperation represents a container operation command
type ContainerOperation struct {
	ContainerID   string            `json:"container_id,omitempty"`
	ContainerName string            `json:"container_name,omitempty"`
	Image         string            `json:"image,omitempty"`
	ImageDigest   string            `json:"image_digest,omitempty"`
	Config        map[string]interface{} `json:"config,omitempty"`
}

// SelfUpdateCommand tells agent to update itself
type SelfUpdateCommand struct {
	NewImage      string `json:"new_image"`
	ImageDigest   string `json:"image_digest"`
}

// UpdateLock is written to /data/update.lock during self-update
type UpdateLock struct {
	Status         string    `json:"status"` // "pulling", "starting", "new_agent_healthy", "failed"
	OldContainerID string    `json:"old_container_id"`
	NewContainerID string    `json:"new_container_id,omitempty"`
	NewImage       string    `json:"new_image"`
	StartedAt      time.Time `json:"started_at"`
	ErrorMessage   string    `json:"error_message,omitempty"`
}

// ContainerStats represents container resource usage
type ContainerStats struct {
	ContainerID string    `json:"container_id"`
	Timestamp   time.Time `json:"timestamp"`
	CPUPercent  float64   `json:"cpu_percent"`
	MemoryUsage uint64    `json:"memory_usage"`
	MemoryLimit uint64    `json:"memory_limit"`
	MemoryPercent float64 `json:"memory_percent"`
	NetworkRx   uint64    `json:"network_rx"`
	NetworkTx   uint64    `json:"network_tx"`
	BlockRead   uint64    `json:"block_read"`
	BlockWrite  uint64    `json:"block_write"`
}

// ContainerEvent represents a Docker container event
type ContainerEvent struct {
	ContainerID   string            `json:"container_id"`
	ContainerName string            `json:"container_name"`
	Image         string            `json:"image"`
	Action        string            `json:"action"` // start, stop, die, health_status
	Status        string            `json:"status,omitempty"`
	Timestamp     time.Time         `json:"timestamp"`
	Attributes    map[string]string `json:"attributes,omitempty"`
}

// ShellSessionCommand represents a shell session command from the backend
type ShellSessionCommand struct {
	Action      string `json:"action"`       // start, data, resize, close
	ContainerID string `json:"container_id"` // Container to exec into
	SessionID   string `json:"session_id"`   // Unique session identifier
	Data        string `json:"data,omitempty"`  // Base64-encoded terminal data (for action=data)
	Cols        int    `json:"cols,omitempty"`  // Terminal columns (for action=resize)
	Rows        int    `json:"rows,omitempty"`  // Terminal rows (for action=resize)
}

// ShellDataEvent represents shell data sent from agent to backend
type ShellDataEvent struct {
	SessionID string `json:"session_id"`         // Session identifier
	Action    string `json:"action"`             // started, data, closed, error
	Data      string `json:"data,omitempty"`     // Base64-encoded terminal output
	Error     string `json:"error,omitempty"`    // Error message (for action=error)
}
