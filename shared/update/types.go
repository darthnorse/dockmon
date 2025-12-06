// Package update provides container update functionality shared between
// the compose-service (for local/mTLS hosts) and the agent (for agent-based hosts).
//
// This consolidates the duplicated update logic that was previously in both:
// - backend/updates/docker_executor.py (Python)
// - agent/internal/handlers/update.go (Go)
package update

import (
	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/network"
)

// UpdateRequest contains all parameters for a container update.
type UpdateRequest struct {
	ContainerID   string        `json:"container_id"`
	NewImage      string        `json:"new_image"`
	StopTimeout   int           `json:"stop_timeout,omitempty"`   // Default: 30s
	HealthTimeout int           `json:"health_timeout,omitempty"` // Default: 120s
	RegistryAuth  *RegistryAuth `json:"registry_auth,omitempty"`  // Optional registry credentials
}

// RegistryAuth contains credentials for authenticating with a Docker registry.
type RegistryAuth struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// UpdateResult contains the outcome of an update operation.
type UpdateResult struct {
	Success          bool     `json:"success"`
	OldContainerID   string   `json:"old_container_id"`
	NewContainerID   string   `json:"new_container_id"`
	ContainerName    string   `json:"container_name"`
	RolledBack       bool     `json:"rolled_back,omitempty"`
	FailedDependents []string `json:"failed_dependents,omitempty"`
	Error            string   `json:"error,omitempty"`
}

// ProgressEvent represents an update progress event for streaming.
type ProgressEvent struct {
	Stage    string `json:"stage"`
	Message  string `json:"message"`
	Progress int    `json:"progress,omitempty"` // 0-100 for stages that support it
}

// LayerProgress represents progress for a single image layer during pull.
type LayerProgress struct {
	ID      string `json:"id"`
	Status  string `json:"status"`
	Current int64  `json:"current"`
	Total   int64  `json:"total"`
	Percent int    `json:"percent"`
}

// PullProgressEvent contains detailed layer progress during image pull.
type PullProgressEvent struct {
	ContainerID     string           `json:"container_id"`
	OverallProgress int              `json:"overall_progress"` // 0-100
	Layers          []*LayerProgress `json:"layers"`
	TotalLayers     int              `json:"total_layers"`
	Summary         string           `json:"summary"`
	SpeedMbps       float64          `json:"speed_mbps,omitempty"`
}

// Update stage constants (aligned with Python backend for compatibility).
const (
	StagePulling     = "pulling"
	StageConfiguring = "configuring"
	StageBackup      = "backup"
	StageCreating    = "creating"
	StageStarting    = "starting"
	StageHealthCheck = "health_check"
	StageDependents  = "dependents"
	StageCleanup     = "cleanup"
	StageCompleted   = "completed"
	StageFailed      = "failed"
	StageRollback    = "rollback"
)

// ExtractedConfig holds the extracted container configuration for recreation.
type ExtractedConfig struct {
	Config           *container.Config
	HostConfig       *container.HostConfig
	NetworkingConfig *network.NetworkingConfig
	AdditionalNets   map[string]*network.EndpointSettings
	ContainerName    string
}

// DependentContainer holds info about a container that depends on another
// via network_mode: container:X
type DependentContainer struct {
	Container      types.ContainerJSON
	Name           string
	ID             string
	Image          string
	OldNetworkMode string
}

// ProgressCallback is called during update to report progress.
type ProgressCallback func(event ProgressEvent)

// PullProgressCallback is called during image pull to report layer progress.
type PullProgressCallback func(event PullProgressEvent)

// UpdaterOptions configures the Updater behavior.
type UpdaterOptions struct {
	// OnProgress is called for stage progress updates
	OnProgress ProgressCallback
	// OnPullProgress is called for detailed pull layer progress
	OnPullProgress PullProgressCallback
	// IsPodman indicates if the Docker daemon is actually Podman
	IsPodman bool
	// SupportsNetworkingConfig indicates if API >= 1.44 (can set network at creation)
	SupportsNetworkingConfig bool
}
