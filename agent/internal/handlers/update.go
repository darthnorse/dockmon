package handlers

import (
	"context"
	"fmt"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/docker"
	dockerTypes "github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/sirupsen/logrus"
)

// UpdateHandler manages container updates
type UpdateHandler struct {
	dockerClient *docker.Client
	log          *logrus.Logger
	sendEvent    func(msgType string, payload interface{}) error
}

// NewUpdateHandler creates a new update handler
func NewUpdateHandler(dockerClient *docker.Client, log *logrus.Logger, sendEvent func(string, interface{}) error) *UpdateHandler {
	return &UpdateHandler{
		dockerClient: dockerClient,
		log:          log,
		sendEvent:    sendEvent,
	}
}

// UpdateRequest contains the parameters for a container update
type UpdateRequest struct {
	ContainerID   string `json:"container_id"`
	NewImage      string `json:"new_image"`
	StopTimeout   int    `json:"stop_timeout,omitempty"`    // Default: 10s
	HealthTimeout int    `json:"health_timeout,omitempty"`  // Default: 30s
}

// UpdateProgress represents update progress events
type UpdateProgress struct {
	ContainerID string `json:"container_id"`
	Stage       string `json:"stage"`
	Message     string `json:"message"`
	Error       string `json:"error,omitempty"`
}

// UpdateContainer performs a rolling update of a container
func (h *UpdateHandler) UpdateContainer(ctx context.Context, req UpdateRequest) error {
	h.log.WithFields(logrus.Fields{
		"container_id": req.ContainerID[:12],
		"new_image":    req.NewImage,
	}).Info("Starting container update")

	// Default timeouts
	if req.StopTimeout == 0 {
		req.StopTimeout = 10
	}
	if req.HealthTimeout == 0 {
		req.HealthTimeout = 30
	}

	// Step 1: Inspect old container to get configuration
	h.sendProgress(req.ContainerID, "inspect", "Inspecting current container")
	oldContainer, err := h.dockerClient.InspectContainer(ctx, req.ContainerID)
	if err != nil {
		h.sendProgressError(req.ContainerID, "inspect", err)
		return fmt.Errorf("failed to inspect container: %w", err)
	}

	// Step 2: Pull new image
	h.sendProgress(req.ContainerID, "pull", fmt.Sprintf("Pulling image %s", req.NewImage))
	if err := h.dockerClient.PullImage(ctx, req.NewImage); err != nil {
		h.sendProgressError(req.ContainerID, "pull", err)
		return fmt.Errorf("failed to pull image: %w", err)
	}

	// Step 3: Create new container with same config
	h.sendProgress(req.ContainerID, "create", "Creating new container")
	newConfig := h.cloneContainerConfig(&oldContainer, req.NewImage)
	newHostConfig := h.cloneHostConfig(oldContainer.HostConfig)

	// Generate new container name (append -new temporarily)
	newName := oldContainer.Name + "-new"

	newContainerID, err := h.dockerClient.CreateContainer(ctx, newConfig, newHostConfig, newName)
	if err != nil {
		h.sendProgressError(req.ContainerID, "create", err)
		return fmt.Errorf("failed to create new container: %w", err)
	}

	h.log.Infof("Created new container %s", newContainerID[:12])

	// Step 4: Start new container
	h.sendProgress(req.ContainerID, "start", "Starting new container")
	if err := h.dockerClient.StartContainer(ctx, newContainerID); err != nil {
		// Cleanup: remove the failed container
		h.dockerClient.RemoveContainer(ctx, newContainerID, true)
		h.sendProgressError(req.ContainerID, "start", err)
		return fmt.Errorf("failed to start new container: %w", err)
	}

	// Step 5: Wait for new container to be healthy
	h.sendProgress(req.ContainerID, "health", "Waiting for new container to be healthy")
	if err := h.waitForHealthy(ctx, newContainerID, req.HealthTimeout); err != nil {
		h.log.WithError(err).Warn("New container failed health check, rolling back")
		// Rollback: stop and remove new container
		h.dockerClient.StopContainer(ctx, newContainerID, req.StopTimeout)
		h.dockerClient.RemoveContainer(ctx, newContainerID, true)
		h.sendProgressError(req.ContainerID, "health", err)
		return fmt.Errorf("new container health check failed: %w", err)
	}

	// Step 6: Stop old container
	h.sendProgress(req.ContainerID, "stop_old", "Stopping old container")
	if err := h.dockerClient.StopContainer(ctx, req.ContainerID, req.StopTimeout); err != nil {
		h.log.WithError(err).Warn("Failed to stop old container (continuing anyway)")
		// Continue anyway - we'll try to remove it
	}

	// Step 7: Remove old container
	h.sendProgress(req.ContainerID, "remove_old", "Removing old container")
	if err := h.dockerClient.RemoveContainer(ctx, req.ContainerID, true); err != nil {
		h.log.WithError(err).Warn("Failed to remove old container")
		// Don't fail the update - new container is running
	}

	// Step 8: Rename new container to original name (optional - Docker will auto-assign name)
	// Note: We can't easily rename via the API, so the new container keeps the -new suffix
	// In production, you might want to implement proper naming strategy

	h.sendProgress(req.ContainerID, "complete", fmt.Sprintf("Update complete, new container: %s", newContainerID[:12]))

	h.log.WithFields(logrus.Fields{
		"old_container": req.ContainerID[:12],
		"new_container": newContainerID[:12],
	}).Info("Container update completed successfully")

	return nil
}

// cloneContainerConfig creates a new container config based on existing container
func (h *UpdateHandler) cloneContainerConfig(inspect *dockerTypes.ContainerJSON, newImage string) *container.Config {
	config := inspect.Config

	return &container.Config{
		Hostname:        config.Hostname,
		Domainname:      config.Domainname,
		User:            config.User,
		AttachStdin:     config.AttachStdin,
		AttachStdout:    config.AttachStdout,
		AttachStderr:    config.AttachStderr,
		Tty:             config.Tty,
		OpenStdin:       config.OpenStdin,
		StdinOnce:       config.StdinOnce,
		Env:             config.Env,
		Cmd:             config.Cmd,
		Image:           newImage, // Use new image
		WorkingDir:      config.WorkingDir,
		Entrypoint:      config.Entrypoint,
		Labels:          config.Labels,
		StopSignal:      config.StopSignal,
		StopTimeout:     config.StopTimeout,
	}
}

// cloneHostConfig creates a new host config based on existing container
func (h *UpdateHandler) cloneHostConfig(hostConfig *container.HostConfig) *container.HostConfig {
	return &container.HostConfig{
		Binds:           hostConfig.Binds,
		ContainerIDFile: hostConfig.ContainerIDFile,
		NetworkMode:     hostConfig.NetworkMode,
		PortBindings:    hostConfig.PortBindings,
		RestartPolicy:   hostConfig.RestartPolicy,
		AutoRemove:      hostConfig.AutoRemove,
		VolumeDriver:    hostConfig.VolumeDriver,
		VolumesFrom:     hostConfig.VolumesFrom,
		CapAdd:          hostConfig.CapAdd,
		CapDrop:         hostConfig.CapDrop,
		DNS:             hostConfig.DNS,
		DNSOptions:      hostConfig.DNSOptions,
		DNSSearch:       hostConfig.DNSSearch,
		ExtraHosts:      hostConfig.ExtraHosts,
		GroupAdd:        hostConfig.GroupAdd,
		IpcMode:         hostConfig.IpcMode,
		Cgroup:          hostConfig.Cgroup,
		Links:           hostConfig.Links,
		OomScoreAdj:     hostConfig.OomScoreAdj,
		PidMode:         hostConfig.PidMode,
		Privileged:      hostConfig.Privileged,
		PublishAllPorts: hostConfig.PublishAllPorts,
		ReadonlyRootfs:  hostConfig.ReadonlyRootfs,
		SecurityOpt:     hostConfig.SecurityOpt,
		UTSMode:         hostConfig.UTSMode,
		UsernsMode:      hostConfig.UsernsMode,
		ShmSize:         hostConfig.ShmSize,
		Sysctls:         hostConfig.Sysctls,
		Runtime:         hostConfig.Runtime,
		Isolation:       hostConfig.Isolation,
		Resources:       hostConfig.Resources,
		Mounts:          hostConfig.Mounts,
		MaskedPaths:     hostConfig.MaskedPaths,
		ReadonlyPaths:   hostConfig.ReadonlyPaths,
		Init:            hostConfig.Init,
	}
}

// waitForHealthy waits for a container to become healthy or timeout
func (h *UpdateHandler) waitForHealthy(ctx context.Context, containerID string, timeout int) error {
	deadline := time.Now().Add(time.Duration(timeout) * time.Second)

	for {
		// Check deadline
		if time.Now().After(deadline) {
			return fmt.Errorf("health check timeout after %ds", timeout)
		}

		// Inspect container
		inspect, err := h.dockerClient.InspectContainer(ctx, containerID)
		if err != nil {
			return fmt.Errorf("failed to inspect container: %w", err)
		}

		// Check if container is still running
		if !inspect.State.Running {
			return fmt.Errorf("container stopped unexpectedly")
		}

		// If no health check defined, wait a few seconds and assume healthy
		if inspect.State.Health == nil {
			h.log.Debug("No health check defined, waiting 5 seconds")
			time.Sleep(5 * time.Second)
			return nil
		}

		// Check health status
		switch inspect.State.Health.Status {
		case "healthy":
			h.log.Info("Container is healthy")
			return nil
		case "unhealthy":
			return fmt.Errorf("container is unhealthy")
		case "starting":
			h.log.Debug("Container health is starting, waiting...")
			time.Sleep(2 * time.Second)
			continue
		default:
			h.log.Debugf("Unknown health status: %s", inspect.State.Health.Status)
			time.Sleep(2 * time.Second)
			continue
		}
	}
}

// sendProgress sends an update progress event
func (h *UpdateHandler) sendProgress(containerID, stage, message string) {
	progress := UpdateProgress{
		ContainerID: containerID,
		Stage:       stage,
		Message:     message,
	}

	if err := h.sendEvent("update_progress", progress); err != nil {
		h.log.WithError(err).Warn("Failed to send update progress")
	}
}

// sendProgressError sends an update progress error event
func (h *UpdateHandler) sendProgressError(containerID, stage string, err error) {
	progress := UpdateProgress{
		ContainerID: containerID,
		Stage:       stage,
		Message:     "Error occurred",
		Error:       err.Error(),
	}

	if sendErr := h.sendEvent("update_progress", progress); sendErr != nil {
		h.log.WithError(sendErr).Warn("Failed to send update progress error")
	}
}
