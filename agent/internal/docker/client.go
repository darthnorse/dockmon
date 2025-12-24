package docker

import (
	"bufio"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"strings"
	"sync"

	sharedDocker "github.com/darthnorse/dockmon-shared/docker"
	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/events"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/api/types/registry"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/darthnorse/dockmon-agent/internal/config"
	"github.com/sirupsen/logrus"
)

// Client wraps the Docker client with agent-specific functionality
type Client struct {
	cli *client.Client
	log *logrus.Logger

	// Cached values for efficiency - detected once, reused
	isPodmanCache   *bool  // Podman detection result
	podmanMu        sync.Mutex
	apiVersionCache string // Docker API version
	apiVersionMu    sync.Mutex
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

// RawClient returns the underlying Docker SDK client.
// This is used by the shared update package which requires the raw client.
func (c *Client) RawClient() *client.Client {
	return c.cli
}

// SystemInfo contains Docker host system information
type SystemInfo struct {
	Hostname        string // Docker host's hostname (not container hostname)
	HostIP          string // Primary host IP (for systemd agents only)
	OSType          string
	OSVersion       string
	KernelVersion   string
	DockerVersion   string
	DaemonStartedAt string
	TotalMemory     int64
	NumCPUs         int
}

// GetHostIP detects the primary non-loopback IPv4 address of the host.
// Filters out Docker/container-related interfaces (docker0, veth*, br-*).
// Returns empty string if no suitable IP is found.
func GetHostIP() string {
	interfaces, err := net.Interfaces()
	if err != nil {
		return ""
	}

	for _, iface := range interfaces {
		// Skip loopback, down interfaces, and Docker-related interfaces
		if iface.Flags&net.FlagLoopback != 0 {
			continue
		}
		if iface.Flags&net.FlagUp == 0 {
			continue
		}

		name := iface.Name
		// Skip Docker/container interfaces
		if name == "docker0" || name == "docker_gwbridge" ||
			strings.HasPrefix(name, "veth") ||
			strings.HasPrefix(name, "br-") ||
			strings.HasPrefix(name, "virbr") {
			continue
		}

		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}

		for _, addr := range addrs {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}

			// Skip loopback and non-IPv4
			if ip == nil || ip.IsLoopback() || ip.To4() == nil {
				continue
			}

			// Found a valid IPv4 address
			return ip.String()
		}
	}

	return ""
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
		Hostname:      info.Name, // Docker host's actual hostname
		HostIP:        GetHostIP(),
		OSType:        info.OSType,
		OSVersion:     info.OperatingSystem,
		KernelVersion: info.KernelVersion,
		DockerVersion: version.Version,
		TotalMemory:   info.MemTotal,
		NumCPUs:       info.NCPU,
	}

	// Get daemon start time from bridge network creation time
	// This matches the approach in monitor.py
	networks, err := c.cli.NetworkList(ctx, network.ListOptions{})
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
	containers, err := c.cli.ContainerList(ctx, container.ListOptions{All: true})
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
	if err := c.cli.ContainerStart(ctx, containerID, container.StartOptions{}); err != nil {
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
	if err := c.cli.ContainerRemove(ctx, containerID, container.RemoveOptions{Force: force}); err != nil {
		return fmt.Errorf("failed to remove container: %w", err)
	}
	return nil
}

// KillContainer sends SIGKILL to a container
func (c *Client) KillContainer(ctx context.Context, containerID string) error {
	if err := c.cli.ContainerKill(ctx, containerID, "SIGKILL"); err != nil {
		return fmt.Errorf("failed to kill container: %w", err)
	}
	return nil
}

// GetContainerLogs retrieves container logs
func (c *Client) GetContainerLogs(ctx context.Context, containerID string, tail string) (string, error) {
	// First, inspect the container to check if it's running with TTY
	// TTY containers return raw logs without multiplexing headers
	inspect, err := c.cli.ContainerInspect(ctx, containerID)
	if err != nil {
		return "", fmt.Errorf("failed to inspect container: %w", err)
	}

	options := container.LogsOptions{
		ShowStdout: true,
		ShowStderr: true,
		Timestamps: true,
		Tail:       tail,
	}

	logs, err := c.cli.ContainerLogs(ctx, containerID, options)
	if err != nil {
		return "", fmt.Errorf("failed to get logs: %w", err)
	}
	defer logs.Close()

	// Check if container is using TTY mode
	// TTY mode returns raw logs, non-TTY uses multiplexed format with 8-byte headers
	if inspect.Config != nil && inspect.Config.Tty {
		// TTY mode: read raw logs directly
		var buf bytes.Buffer
		if _, err := io.Copy(&buf, logs); err != nil {
			return "", fmt.Errorf("failed to read logs: %w", err)
		}
		return buf.String(), nil
	}

	// Non-TTY mode: demultiplex stdout/stderr streams
	var stdout, stderr bytes.Buffer
	if _, err := stdcopy.StdCopy(&stdout, &stderr, logs); err != nil {
		return "", fmt.Errorf("failed to demultiplex logs: %w", err)
	}

	// Combine stdout and stderr
	result := stdout.String() + stderr.String()
	return result, nil
}

// ContainerStats gets a stats stream for a container
func (c *Client) ContainerStats(ctx context.Context, containerID string, stream bool) (container.StatsResponseReader, error) {
	return c.cli.ContainerStats(ctx, containerID, stream)
}

// WatchEvents watches Docker events
func (c *Client) WatchEvents(ctx context.Context) (<-chan events.Message, <-chan error) {
	eventChan, errChan := c.cli.Events(ctx, events.ListOptions{})
	return eventChan, errChan
}

// PullImage pulls a Docker image
func (c *Client) PullImage(ctx context.Context, imageName string) error {
	reader, err := c.cli.ImagePull(ctx, imageName, image.PullOptions{})
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

// PullProgress represents a layer progress event from Docker image pull.
// Docker sends JSON lines with progress info for each layer.
type PullProgress struct {
	ID             string `json:"id"`              // Layer ID (e.g., "a1b2c3d4e5f6")
	Status         string `json:"status"`          // Status message (e.g., "Downloading", "Pull complete")
	Progress       string `json:"progress"`        // Progress bar string (e.g., "[=====>   ]")
	ProgressDetail struct {
		Current int64 `json:"current"` // Bytes downloaded
		Total   int64 `json:"total"`   // Total bytes
	} `json:"progressDetail"`
}

// RegistryAuth contains credentials for authenticating with a Docker registry.
// Used when pulling images from private registries.
type RegistryAuth struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// encodeRegistryAuth encodes registry credentials to base64 JSON format
// required by Docker's ImagePull API.
func encodeRegistryAuth(auth *RegistryAuth) string {
	if auth == nil || auth.Username == "" {
		return ""
	}
	authConfig := registry.AuthConfig{
		Username: auth.Username,
		Password: auth.Password,
	}
	encodedJSON, err := json.Marshal(authConfig)
	if err != nil {
		return ""
	}
	return base64.URLEncoding.EncodeToString(encodedJSON)
}

// PullImageWithProgress pulls a Docker image and calls the callback for each progress event.
// Progress reporting is best-effort - parsing errors don't fail the pull.
// auth is optional - pass nil for public registries.
func (c *Client) PullImageWithProgress(ctx context.Context, imageName string, auth *RegistryAuth, onProgress func(PullProgress)) error {
	pullOpts := image.PullOptions{}
	if encodedAuth := encodeRegistryAuth(auth); encodedAuth != "" {
		pullOpts.RegistryAuth = encodedAuth
		c.log.Debug("Using registry authentication for image pull")
	}

	reader, err := c.cli.ImagePull(ctx, imageName, pullOpts)
	if err != nil {
		return fmt.Errorf("failed to pull image: %w", err)
	}
	defer reader.Close()

	// Parse JSON lines from the progress stream
	scanner := bufio.NewScanner(reader)
	// Increase buffer size for large progress messages
	buf := make([]byte, 64*1024)
	scanner.Buffer(buf, 1024*1024)

	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}

		var progress PullProgress
		if err := json.Unmarshal(line, &progress); err != nil {
			// Best effort - skip malformed lines, don't fail the pull
			continue
		}

		// Call progress callback (best effort, ignore panics)
		if onProgress != nil {
			func() {
				defer func() { recover() }()
				onProgress(progress)
			}()
		}
	}

	// Scanner error doesn't fail the pull - image may already be pulled
	if err := scanner.Err(); err != nil {
		c.log.WithError(err).Debug("Scanner error during image pull (non-fatal)")
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

// RenameContainer renames a container
func (c *Client) RenameContainer(ctx context.Context, containerID, newName string) error {
	if err := c.cli.ContainerRename(ctx, containerID, newName); err != nil {
		return fmt.Errorf("failed to rename container: %w", err)
	}
	return nil
}

// ConnectNetwork connects a container to a network with endpoint configuration.
// Used for multi-network containers since Docker only allows one network at creation.
func (c *Client) ConnectNetwork(
	ctx context.Context,
	containerID string,
	networkID string,
	endpointConfig *network.EndpointSettings,
) error {
	return c.cli.NetworkConnect(ctx, networkID, containerID, endpointConfig)
}

// IsPodman returns true if connected to Podman instead of Docker.
// Result is cached after first detection for efficiency.
func (c *Client) IsPodman(ctx context.Context) (bool, error) {
	c.podmanMu.Lock()
	defer c.podmanMu.Unlock()

	// Return cached result if available
	if c.isPodmanCache != nil {
		return *c.isPodmanCache, nil
	}

	info, err := c.cli.Info(ctx)
	if err != nil {
		return false, fmt.Errorf("failed to get Docker info: %w", err)
	}

	isPodman := false

	// Check multiple indicators for reliability:
	// 1. Operating system contains "podman"
	osLower := strings.ToLower(info.OperatingSystem)
	if strings.Contains(osLower, "podman") {
		isPodman = true
	}

	// 2. Server version components contain "podman"
	if !isPodman {
		version, err := c.cli.ServerVersion(ctx)
		if err == nil {
			for _, comp := range version.Components {
				if strings.ToLower(comp.Name) == "podman" {
					isPodman = true
					break
				}
			}
		}
	}

	// Cache the result
	c.isPodmanCache = &isPodman
	return isPodman, nil
}

// GetContainerByName finds a container by name and returns its ID.
// Returns empty string if not found.
func (c *Client) GetContainerByName(ctx context.Context, name string) (string, error) {
	// Remove leading slash if present
	name = strings.TrimPrefix(name, "/")

	containers, err := c.cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("name", "^/"+name+"$")),
	})
	if err != nil {
		return "", fmt.Errorf("failed to list containers: %w", err)
	}

	if len(containers) == 0 {
		return "", nil
	}

	return containers[0].ID, nil
}

// ListAllContainers returns all containers (running and stopped).
// This is the typed version that returns types.Container slice.
func (c *Client) ListAllContainers(ctx context.Context) ([]types.Container, error) {
	return c.cli.ContainerList(ctx, container.ListOptions{All: true})
}

// GetImageLabels returns the labels defined in an image.
func (c *Client) GetImageLabels(ctx context.Context, imageRef string) (map[string]string, error) {
	img, _, err := c.cli.ImageInspectWithRaw(ctx, imageRef)
	if err != nil {
		return nil, fmt.Errorf("failed to inspect image: %w", err)
	}

	if img.Config == nil || img.Config.Labels == nil {
		return make(map[string]string), nil
	}

	return img.Config.Labels, nil
}

// CreateContainerWithNetwork creates a new container with full network configuration.
// networkConfig can be nil for containers using default bridge networking.
func (c *Client) CreateContainerWithNetwork(
	ctx context.Context,
	config *container.Config,
	hostConfig *container.HostConfig,
	networkConfig *network.NetworkingConfig,
	name string,
) (string, error) {
	resp, err := c.cli.ContainerCreate(ctx, config, hostConfig, networkConfig, nil, name)
	if err != nil {
		return "", fmt.Errorf("failed to create container: %w", err)
	}
	return resp.ID, nil
}

// GetAPIVersion returns the Docker API version string (e.g., "1.44").
// Result is cached after first call for efficiency.
func (c *Client) GetAPIVersion(ctx context.Context) (string, error) {
	c.apiVersionMu.Lock()
	defer c.apiVersionMu.Unlock()

	// Return cached result if available
	if c.apiVersionCache != "" {
		return c.apiVersionCache, nil
	}

	version, err := c.cli.ServerVersion(ctx)
	if err != nil {
		return "", fmt.Errorf("failed to get server version: %w", err)
	}

	c.apiVersionCache = version.APIVersion
	return c.apiVersionCache, nil
}

// SupportsNetworkingConfig returns true if the Docker API supports
// networking_config at container creation (API >= 1.44).
// This determines whether static IPs can be set at creation or require
// manual network connection post-creation.
func (c *Client) SupportsNetworkingConfig(ctx context.Context) (bool, error) {
	apiVersion, err := c.GetAPIVersion(ctx)
	if err != nil {
		return false, err
	}

	// Parse version string (e.g., "1.44" -> major=1, minor=44)
	parts := strings.Split(apiVersion, ".")
	if len(parts) < 2 {
		return false, fmt.Errorf("invalid API version format: %s", apiVersion)
	}

	major, err := strconv.Atoi(parts[0])
	if err != nil {
		return false, fmt.Errorf("invalid major version: %s", parts[0])
	}

	minor, err := strconv.Atoi(parts[1])
	if err != nil {
		return false, fmt.Errorf("invalid minor version: %s", parts[1])
	}

	// API >= 1.44 supports networking_config at creation
	if major > 1 || (major == 1 && minor >= 44) {
		return true, nil
	}

	return false, nil
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
