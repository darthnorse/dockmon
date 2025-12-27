// Package compose provides Docker Compose SDK wrapper functionality
// shared between the compose-service and agent.
package compose

// DeployRequest is sent from the caller (Python backend or agent) to execute a compose deployment
type DeployRequest struct {
	// Deployment identification
	DeploymentID string `json:"deployment_id"`
	ProjectName  string `json:"project_name"`

	// Compose content
	ComposeYAML string            `json:"compose_yaml"`
	Environment map[string]string `json:"environment,omitempty"`
	Profiles    []string          `json:"profiles,omitempty"`

	// Action
	Action        string `json:"action"`                   // "up", "down", "restart"
	RemoveVolumes bool   `json:"remove_volumes,omitempty"` // Only for "down" action

	// Redeploy options (for "up" action)
	ForceRecreate bool `json:"force_recreate,omitempty"` // Force recreate containers even if unchanged
	PullImages    bool `json:"pull_images,omitempty"`    // Pull images before starting

	// Health check options
	WaitForHealthy bool `json:"wait_for_healthy,omitempty"`
	HealthTimeout  int  `json:"health_timeout,omitempty"` // seconds, default 60

	// Timeout for the entire operation (seconds)
	Timeout int `json:"timeout,omitempty"` // default 1800 (30 minutes)

	// Docker connection (determines local vs remote)
	// Empty DockerHost means use local socket
	DockerHost string `json:"docker_host,omitempty"` // e.g., "tcp://192.168.1.100:2376"
	TLSCACert  string `json:"tls_ca_cert,omitempty"` // PEM content
	TLSCert    string `json:"tls_cert,omitempty"`    // PEM content
	TLSKey     string `json:"tls_key,omitempty"`     // PEM content

	// Registry authentication
	RegistryCredentials []RegistryCredential `json:"registry_credentials,omitempty"`
}

// RegistryCredential holds credentials for a Docker registry.
// Used to authenticate when pulling images from private registries.
type RegistryCredential struct {
	RegistryURL string `json:"registry_url"`
	Username    string `json:"username"`
	Password    string `json:"password"`
}

// DeployResult is returned from a compose deployment
type DeployResult struct {
	DeploymentID   string                   `json:"deployment_id"`
	Success        bool                     `json:"success"`
	PartialSuccess bool                     `json:"partial_success,omitempty"`
	Services       map[string]ServiceResult `json:"services,omitempty"`
	FailedServices []string                 `json:"failed_services,omitempty"`
	Error          *ComposeError            `json:"error,omitempty"`
}

// ServiceResult contains info about a deployed service
type ServiceResult struct {
	ContainerID   string `json:"container_id"`   // SHORT ID (12 chars)
	ContainerName string `json:"container_name"`
	Image         string `json:"image"`
	Status        string `json:"status"`
	Error         string `json:"error,omitempty"`
	// RestartPolicy for determining if exit is acceptable (Issue #110)
	// Values: "", "no", "on-failure", "always", "unless-stopped"
	RestartPolicy string `json:"restart_policy,omitempty"`
	// ExitCode from the container (only set for exited containers)
	ExitCode int `json:"exit_code,omitempty"`
}

// ProgressStage represents the current stage of deployment
type ProgressStage string

const (
	StageValidating     ProgressStage = "validating"       // 5%
	StageParsing        ProgressStage = "parsing"          // 10%
	StageCreatingNets   ProgressStage = "creating_networks" // 15%
	StageCreatingVols   ProgressStage = "creating_volumes" // 20%
	StagePullingImage   ProgressStage = "pulling_image"    // 25-60% (per-service)
	StageCreating       ProgressStage = "creating"         // 60-80% (per-service)
	StageStarting       ProgressStage = "starting"         // 80-90% (per-service)
	StageHealthCheck    ProgressStage = "health_check"     // 90-95%
	StageCompleted      ProgressStage = "completed"        // 100%
	StageFailed         ProgressStage = "failed"           // 100%
)

// Legacy stage constants for backward compatibility with agent
const (
	DeployStageStarting      = "starting"
	DeployStageExecuting     = "executing"
	DeployStageWaitingHealth = "waiting_for_health"
	DeployStageCompleted     = "completed"
	DeployStageFailed        = "failed"
)

// ProgressEvent represents a progress update during deployment
type ProgressEvent struct {
	Stage      ProgressStage `json:"stage"`
	Progress   int           `json:"progress"` // 0-100
	Message    string        `json:"message"`
	Service    string        `json:"service,omitempty"`     // Current service (for per-service stages)
	ServiceIdx int           `json:"service_idx,omitempty"` // 1-based index
	TotalSvcs  int           `json:"total_services,omitempty"`

	// Layer-level pull progress (matches existing ImagePullProgress format)
	Layers         []LayerProgress `json:"layers,omitempty"`           // Per-layer status
	TotalLayers    int             `json:"total_layers,omitempty"`
	SpeedMbps      float64         `json:"speed_mbps,omitempty"`       // Download speed in MB/s
	OverallPercent int             `json:"overall_progress,omitempty"` // Bytes-based overall %
}

// LayerProgress tracks download progress for a single image layer
type LayerProgress struct {
	ID      string `json:"id"`      // Layer short ID
	Status  string `json:"status"`  // Downloading, Extracting, Pull complete, Already exists
	Current int64  `json:"current"` // Bytes downloaded
	Total   int64  `json:"total"`   // Total bytes
	Percent int    `json:"percent"` // 0-100
}

// ProgressCallback is called during deployment to report progress
type ProgressCallback func(event ProgressEvent)

// Option configures a Service
type Option func(*Service)

// WithProgressCallback sets the progress callback for deployment updates
func WithProgressCallback(fn ProgressCallback) Option {
	return func(s *Service) {
		s.progressFn = fn
	}
}

// ServiceStatus represents the status of a single service during deployment
type ServiceStatus struct {
	Name    string `json:"name"`
	Status  string `json:"status"`
	Image   string `json:"image,omitempty"`
	Message string `json:"message,omitempty"`
}
