package config

import (
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Config holds all agent configuration
type Config struct {
	// DockMon connection
	DockMonURL         string
	RegistrationToken  string
	PermanentToken     string
	InsecureSkipVerify bool

	// Docker connection
	DockerHost       string
	DockerCertPath   string
	DockerTLSVerify  bool

	// Agent identity
	AgentVersion     string
	ProtoVersion     string
	AgentName        string
	// ForceUniqueRegistration tells the backend to skip its engine_id
	// uniqueness check, which lets cloned VMs (sharing /var/lib/docker/engine-id)
	// register as distinct hosts. Requires AGENT_NAME to also be set.
	ForceUniqueRegistration bool

	// Reconnection settings
	ReconnectInitial time.Duration
	ReconnectMax     time.Duration

	// Update settings
	DataPath         string
	UpdateLockPath   string
	UpdateTimeout    time.Duration

	// Stack storage - persistent directory for compose deployments
	StacksDir        string
	// Host-side stacks path for resolving relative bind mounts in containerized agents
	HostStacksDir    string

	// Logging
	LogLevel         string
	LogJSON          bool
}

// LoadFromEnv loads configuration from environment variables
func LoadFromEnv() (*Config, error) {
	cfg := &Config{
		// Required
		DockMonURL:         os.Getenv("DOCKMON_URL"),
		RegistrationToken:  os.Getenv("REGISTRATION_TOKEN"),
		PermanentToken:     os.Getenv("PERMANENT_TOKEN"),
		InsecureSkipVerify: getEnvBool("INSECURE_SKIP_VERIFY", false),

		// Docker/Podman (auto-detects socket if DOCKER_HOST not set)
		DockerHost:       getEnvOrDefault("DOCKER_HOST", detectContainerSocket()),
		DockerCertPath:   os.Getenv("DOCKER_CERT_PATH"),
		DockerTLSVerify:  getEnvBool("DOCKER_TLS_VERIFY", false),

		// Protocol
		// 1.1: agent dual-sends container_stats to stats-service /api/stats/ws/ingest
		// for historical persistence (spec §10). Older agents (1.0) continue to feed
		// Python's in-memory buffer only — live sparklines still work but no history.
		ProtoVersion:     getEnvOrDefault("PROTO_VERSION", "1.1"),

		// Optional display-name override sent during registration. If empty, agent
		// falls back to Docker daemon hostname -> OS hostname -> engine_id.
		AgentName:        strings.TrimSpace(os.Getenv("AGENT_NAME")),

		// Opt-in for cloned-VM scenarios: tells the backend to skip the engine_id
		// uniqueness check so two clones (which share engine_id) can both register
		// as distinct hosts. Has no effect unless AGENT_NAME is also set.
		ForceUniqueRegistration: getEnvBool("FORCE_UNIQUE_REGISTRATION", false),

		// Reconnection (exponential backoff: 1s → 60s)
		ReconnectInitial: getEnvDuration("RECONNECT_INITIAL", 1*time.Second),
		ReconnectMax:     getEnvDuration("RECONNECT_MAX", 60*time.Second),

		// Update
		DataPath:         getEnvOrDefault("DATA_PATH", "/data"),
		UpdateTimeout:    getEnvDuration("UPDATE_TIMEOUT", 120*time.Second),

		// Logging
		LogLevel:         getEnvOrDefault("LOG_LEVEL", "info"),
		LogJSON:          getEnvBool("LOG_JSON", true),
	}

	// Derived paths
	cfg.UpdateLockPath = filepath.Join(cfg.DataPath, "update.lock")

	// Stack storage directory - default to $DATA_PATH/stacks, allow override with AGENT_STACKS_DIR
	cfg.StacksDir = getEnvOrDefault("AGENT_STACKS_DIR", filepath.Join(cfg.DataPath, "stacks"))
	cfg.HostStacksDir = os.Getenv("HOST_STACKS_DIR")

	// Validation
	if cfg.DockMonURL == "" {
		return nil, fmt.Errorf("DOCKMON_URL is required")
	}

	// Backend caps host name at 255 chars; reject early with a clear error
	// instead of letting registration fail silently in the reconnect loop.
	if len(cfg.AgentName) > 255 {
		return nil, fmt.Errorf("AGENT_NAME exceeds 255 characters (got %d)", len(cfg.AgentName))
	}

	// Try to load permanent token from persisted file
	if cfg.PermanentToken == "" {
		tokenPath := filepath.Join(cfg.DataPath, "permanent_token")
		if data, err := os.ReadFile(tokenPath); err == nil {
			cfg.PermanentToken = strings.TrimSpace(string(data))
		}
	}

	if cfg.RegistrationToken == "" && cfg.PermanentToken == "" {
		return nil, fmt.Errorf("either REGISTRATION_TOKEN or PERMANENT_TOKEN is required")
	}

	return cfg, nil
}

// getEnvOrDefault returns environment variable value or default
func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// getEnvBool returns environment variable as boolean
func getEnvBool(key string, defaultValue bool) bool {
	if value := os.Getenv(key); value != "" {
		if parsed, err := strconv.ParseBool(value); err == nil {
			return parsed
		}
	}
	return defaultValue
}

// getEnvDuration returns environment variable as duration
func getEnvDuration(key string, defaultValue time.Duration) time.Duration {
	if value := os.Getenv(key); value != "" {
		if parsed, err := time.ParseDuration(value); err == nil {
			return parsed
		}
	}
	return defaultValue
}

// detectContainerSocket finds the first available container runtime socket.
// Checks common locations for Docker and Podman in order of preference.
func detectContainerSocket() string {
	// Common socket paths in order of preference
	sockets := []string{
		"/var/run/docker.sock",     // Docker (most common)
		"/run/docker.sock",         // Docker (alternative location)
		"/run/podman/podman.sock",  // Podman rootful
	}

	for _, sock := range sockets {
		if info, err := os.Stat(sock); err == nil && (info.Mode()&os.ModeSocket) != 0 {
			return "unix://" + sock
		}
	}

	// Fallback to Docker default (will error if not available, but that's expected)
	return "unix:///var/run/docker.sock"
}
