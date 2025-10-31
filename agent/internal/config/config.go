package config

import (
	"fmt"
	"os"
	"strconv"
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

	// Reconnection settings
	ReconnectInitial time.Duration
	ReconnectMax     time.Duration

	// Update settings
	DataPath         string
	UpdateLockPath   string
	UpdateTimeout    time.Duration

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

		// Docker (defaults work for standard socket)
		DockerHost:       getEnvOrDefault("DOCKER_HOST", "unix:///var/run/docker.sock"),
		DockerCertPath:   os.Getenv("DOCKER_CERT_PATH"),
		DockerTLSVerify:  getEnvBool("DOCKER_TLS_VERIFY", false),

		// Agent identity
		AgentVersion:     getEnvOrDefault("AGENT_VERSION", "2.2.0"),
		ProtoVersion:     getEnvOrDefault("PROTO_VERSION", "1.0"),

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
	cfg.UpdateLockPath = cfg.DataPath + "/update.lock"

	// Validation
	if cfg.DockMonURL == "" {
		return nil, fmt.Errorf("DOCKMON_URL is required")
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
