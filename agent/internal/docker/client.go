package docker

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"os"

	sharedDocker "github.com/darthnorse/dockmon-shared/docker"
	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/events"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/darthnorse/dockmon-agent/internal/config"
	"github.com/sirupsen/logrus"
)

// Client wraps the Docker client with agent-specific functionality
type Client struct {
	cli *client.Client
	log *logrus.Logger
}

// NewClient creates a new Docker client using shared package
func NewClient(cfg *config.Config, log *logrus.Logger) (*Client, error) {
	var cli *client.Client
	var err error

	// Use shared package for client creation
	if cfg.DockerHost == "" || cfg.DockerHost == "unix:///var/run/docker.sock" {
		// Local Docker socket
		cli, err = sharedDocker.CreateLocalClient()
	} else if cfg.DockerTLSVerify && cfg.DockerCertPath != "" {
		// Remote with TLS - need to read cert files
		// For now, this is simplified - in production we'd read the PEM files
		return nil, fmt.Errorf("TLS configuration not yet implemented for agent")
	} else {
		// Remote without TLS (or basic connection)
		cli, err = sharedDocker.CreateRemoteClient(cfg.DockerHost, "", "", "")
	}

	if err != nil {
		return nil, fmt.Errorf("failed to create Docker client: %w", err)
	}

	return &Client{
		cli: cli,
		log: log,
	}, nil
}

// Close closes the Docker client
func (c *Client) Close() error {
	return c.cli.Close()
}

// SystemInfo contains Docker host system information
type SystemInfo struct {
	Hostname        string  // Docker host's hostname (not container hostname)
	OSType          string
	OSVersion       string
	KernelVersion   string
	DockerVersion   string
	DaemonStartedAt string
	TotalMemory     int64
	NumCPUs         int
}

// GetEngineID returns the unique Docker engine ID
func (c *Client) GetEngineID(ctx context.Context) (string, error) {
	info, err := c.cli.Info(ctx)
	if err != nil {
		return "", fmt.Errorf("failed to get Docker info: %w", err)
	}
	return info.ID, nil
}

// GetSystemInfo collects system information from Docker daemon
// Matches the data collected by legacy hosts in monitor.py
func (c *Client) GetSystemInfo(ctx context.Context) (*SystemInfo, error) {
	// Get system info from Docker
	info, err := c.cli.Info(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get Docker info: %w", err)
	}

	// Get version info
	version, err := c.cli.ServerVersion(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to get Docker version: %w", err)
	}

	sysInfo := &SystemInfo{
		Hostname:      info.Name,  // Docker host's actual hostname
		OSType:        info.OSType,
		OSVersion:     info.OperatingSystem,
		KernelVersion: info.KernelVersion,
		DockerVersion: version.Version,
		TotalMemory:   info.MemTotal,
		NumCPUs:       info.NCPU,
	}

	// Get daemon start time from bridge network creation time
	// This matches the approach in monitor.py
	networks, err := c.cli.NetworkList(ctx, types.NetworkListOptions{})
	if err == nil {
		for _, network := range networks {
			if network.Name == "bridge" {
				sysInfo.DaemonStartedAt = network.Created.Format("2006-01-02T15:04:05.999999999Z07:00")
				break
			}
		}
	}
	// Silently ignore network errors - daemon_started_at is optional

	return sysInfo, nil
}

// GetMyContainerID attempts to determine the agent's own container ID
// by reading /proc/self/cgroup
func (c *Client) GetMyContainerID(ctx context.Context) (string, error) {
	// Read cgroup file to get container ID
	data, err := os.ReadFile("/proc/self/cgroup")
	if err != nil {
		return "", fmt.Errorf("failed to read cgroup: %w", err)
	}

	// Parse container ID from cgroup
	// Format: 0::/docker/<container_id>
	// or: 12:cpu,cpuacct:/docker/<container_id>
	containerID := parseContainerIDFromCgroup(string(data))
	if containerID == "" {
		return "", fmt.Errorf("could not parse container ID from cgroup")
	}

	return containerID, nil
}

// ContainerWithDigest extends types.Container with RepoDigests
type ContainerWithDigest struct {
	types.Container
	RepoDigests []string `json:"RepoDigests"`
}

// ListContainers lists all containers with image digest information
func (c *Client) ListContainers(ctx context.Context) ([]ContainerWithDigest, error) {
	containers, err := c.cli.ContainerList(ctx, types.ContainerListOptions{All: true})
	if err != nil {
		return nil, fmt.Errorf("failed to list containers: %w", err)
	}

	// Enhance with RepoDigests from image inspection
	result := make([]ContainerWithDigest, 0, len(containers))
	for _, container := range containers {
		enhanced := ContainerWithDigest{
			Container:   container,
			RepoDigests: []string{},
		}

		// Get image info to extract RepoDigests
		// This is needed for update checking - backend can't query agent hosts directly
		if container.ImageID != "" {
			imageInfo, _, err := c.cli.ImageInspectWithRaw(ctx, container.ImageID)
			if err == nil && imageInfo.RepoDigests != nil {
				enhanced.RepoDigests = imageInfo.RepoDigests
			}
			// Silently ignore errors - RepoDigests are optional (e.g., locally built images)
		}

		result = append(result, enhanced)
	}

	return result, nil
}

// InspectContainer inspects a container
func (c *Client) InspectContainer(ctx context.Context, containerID string) (types.ContainerJSON, error) {
	inspect, err := c.cli.ContainerInspect(ctx, containerID)
	if err != nil {
		return types.ContainerJSON{}, fmt.Errorf("failed to inspect container: %w", err)
	}
	return inspect, nil
}

// StartContainer starts a container
func (c *Client) StartContainer(ctx context.Context, containerID string) error {
	if err := c.cli.ContainerStart(ctx, containerID, types.ContainerStartOptions{}); err != nil {
		return fmt.Errorf("failed to start container: %w", err)
	}
	return nil
}

// StopContainer stops a container
func (c *Client) StopContainer(ctx context.Context, containerID string, timeout int) error {
	stopTimeout := timeout
	if err := c.cli.ContainerStop(ctx, containerID, container.StopOptions{Timeout: &stopTimeout}); err != nil {
		return fmt.Errorf("failed to stop container: %w", err)
	}
	return nil
}

// RestartContainer restarts a container
func (c *Client) RestartContainer(ctx context.Context, containerID string, timeout int) error {
	stopTimeout := timeout
	if err := c.cli.ContainerRestart(ctx, containerID, container.StopOptions{Timeout: &stopTimeout}); err != nil {
		return fmt.Errorf("failed to restart container: %w", err)
	}
	return nil
}

// RemoveContainer removes a container
func (c *Client) RemoveContainer(ctx context.Context, containerID string, force bool) error {
	if err := c.cli.ContainerRemove(ctx, containerID, types.ContainerRemoveOptions{Force: force}); err != nil {
		return fmt.Errorf("failed to remove container: %w", err)
	}
	return nil
}

// GetContainerLogs retrieves container logs
func (c *Client) GetContainerLogs(ctx context.Context, containerID string, tail string) (string, error) {
	options := types.ContainerLogsOptions{
		ShowStdout: true,
		ShowStderr: true,
		Tail:       tail,
	}

	logs, err := c.cli.ContainerLogs(ctx, containerID, options)
	if err != nil {
		return "", fmt.Errorf("failed to get logs: %w", err)
	}
	defer logs.Close()

	// Docker returns logs in a multiplexed stream format with 8-byte headers
	// Use stdcopy to demultiplex stdout and stderr streams
	var stdout, stderr bytes.Buffer
	if _, err := stdcopy.StdCopy(&stdout, &stderr, logs); err != nil {
		return "", fmt.Errorf("failed to demultiplex logs: %w", err)
	}

	// Combine stdout and stderr (interleaved, similar to Docker CLI)
	result := stdout.String() + stderr.String()
	return result, nil
}

// ContainerStats gets a stats stream for a container
func (c *Client) ContainerStats(ctx context.Context, containerID string, stream bool) (types.ContainerStats, error) {
	return c.cli.ContainerStats(ctx, containerID, stream)
}

// WatchEvents watches Docker events
func (c *Client) WatchEvents(ctx context.Context) (<-chan events.Message, <-chan error) {
	eventChan, errChan := c.cli.Events(ctx, types.EventsOptions{})
	return eventChan, errChan
}

// PullImage pulls a Docker image
func (c *Client) PullImage(ctx context.Context, image string) error {
	reader, err := c.cli.ImagePull(ctx, image, types.ImagePullOptions{})
	if err != nil {
		return fmt.Errorf("failed to pull image: %w", err)
	}
	defer reader.Close()

	// Read to EOF to ensure pull completes
	_, err = io.Copy(io.Discard, reader)
	if err != nil {
		return fmt.Errorf("failed to read pull response: %w", err)
	}

	return nil
}

// CreateContainer creates a new container
func (c *Client) CreateContainer(ctx context.Context, config *container.Config, hostConfig *container.HostConfig, name string) (string, error) {
	resp, err := c.cli.ContainerCreate(ctx, config, hostConfig, nil, nil, name)
	if err != nil {
		return "", fmt.Errorf("failed to create container: %w", err)
	}
	return resp.ID, nil
}

// parseContainerIDFromCgroup extracts container ID from /proc/self/cgroup
func parseContainerIDFromCgroup(data string) string {
	// Handles multiple cgroup formats (v1 and v2)
	// Example formats:
	// cgroup v1: 12:cpu,cpuacct:/docker/abc123...
	// cgroup v2: 0::/docker/abc123...
	// systemd:   0::/system.slice/docker-abc123.scope
	// podman:    0::/user.slice/user-1000.slice/user@1000.service/user.slice/libpod-abc123.scope

	lines := splitLines(data)
	for _, line := range lines {
		if len(line) == 0 {
			continue
		}

		// Method 1: Try /docker/ prefix (cgroup v1/v2)
		dockerIdx := findString(line, "/docker/")
		if dockerIdx != -1 {
			idStart := dockerIdx + len("/docker/")
			if idStart < len(line) {
				// Extract container ID until next slash or end
				idEnd := idStart
				for idEnd < len(line) && line[idEnd] != '/' && line[idEnd] != '\n' {
					idEnd++
				}
				if idEnd > idStart {
					return line[idStart:idEnd]
				}
			}
		}

		// Method 2: Try docker-<id>.scope pattern (systemd cgroup v2)
		scopeIdx := findString(line, "docker-")
		if scopeIdx != -1 {
			idStart := scopeIdx + len("docker-")
			if idStart < len(line) {
				// Extract container ID until .scope
				idEnd := idStart
				for idEnd < len(line) && line[idEnd] != '.' && line[idEnd] != '\n' {
					idEnd++
				}
				// Verify it ends with .scope
				if idEnd > idStart && idEnd+6 <= len(line) {
					if line[idEnd:idEnd+6] == ".scope" {
						return line[idStart:idEnd]
					}
				}
			}
		}

		// Method 3: Try /libpod-<id>.scope pattern (Podman)
		podmanIdx := findString(line, "/libpod-")
		if podmanIdx != -1 {
			idStart := podmanIdx + len("/libpod-")
			if idStart < len(line) {
				idEnd := idStart
				for idEnd < len(line) && line[idEnd] != '.' && line[idEnd] != '\n' {
					idEnd++
				}
				if idEnd > idStart && idEnd+6 <= len(line) {
					if line[idEnd:idEnd+6] == ".scope" {
						return line[idStart:idEnd]
					}
				}
			}
		}
	}

	return ""
}

// Helper functions to avoid importing strings package
func splitLines(s string) []string {
	var lines []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			lines = append(lines, s[start:i])
			start = i + 1
		}
	}
	if start < len(s) {
		lines = append(lines, s[start:])
	}
	return lines
}

func findString(s, substr string) int {
	if len(substr) == 0 {
		return 0
	}
	if len(substr) > len(s) {
		return -1
	}
	for i := 0; i <= len(s)-len(substr); i++ {
		match := true
		for j := 0; j < len(substr); j++ {
			if s[i+j] != substr[j] {
				match = false
				break
			}
		}
		if match {
			return i
		}
	}
	return -1
}
