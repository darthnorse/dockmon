package handlers

import (
	"context"

	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/darthnorse/dockmon-shared/update"
	"github.com/sirupsen/logrus"
)

// safeShortID safely truncates a container ID to 12 characters.
// Returns the original string if it's shorter than 12 characters.
func safeShortID(id string) string {
	if len(id) >= 12 {
		return id[:12]
	}
	return id
}

// UpdateHandler manages container updates using the shared update package.
type UpdateHandler struct {
	dockerClient *docker.Client
	log          *logrus.Logger
	sendEvent    func(msgType string, payload interface{}) error
	updater      *update.Updater
}

// UpdateRequest contains the parameters for a container update
type UpdateRequest struct {
	ContainerID   string        `json:"container_id"`
	NewImage      string        `json:"new_image"`
	StopTimeout   int           `json:"stop_timeout,omitempty"`   // Default: 30s
	HealthTimeout int           `json:"health_timeout,omitempty"` // Default: 120s (match Python default)
	RegistryAuth  *RegistryAuth `json:"registry_auth,omitempty"`  // Optional registry credentials
}

// RegistryAuth contains credentials for authenticating with a Docker registry.
// Passed from backend when pulling images from private registries.
type RegistryAuth struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// UpdateResult contains the result of an update operation
type UpdateResult struct {
	OldContainerID   string   `json:"old_container_id"`
	NewContainerID   string   `json:"new_container_id"`
	ContainerName    string   `json:"container_name"`
	FailedDependents []string `json:"failed_dependents,omitempty"`
}

// NewUpdateHandler creates a new update handler using the shared update package.
func NewUpdateHandler(
	ctx context.Context,
	dockerClient *docker.Client,
	log *logrus.Logger,
	sendEvent func(string, interface{}) error,
) (*UpdateHandler, error) {
	// Detect runtime options using the shared package
	options := update.DetectOptions(ctx, dockerClient.RawClient(), log)

	// Create updater from shared package (callbacks will be set per-update)
	updater := update.NewUpdater(dockerClient.RawClient(), log, options)

	return &UpdateHandler{
		dockerClient: dockerClient,
		log:          log,
		sendEvent:    sendEvent,
		updater:      updater,
	}, nil
}

// UpdateContainer performs a rolling update of a container using the shared update package.
// Returns the update result with old/new container IDs.
func (h *UpdateHandler) UpdateContainer(ctx context.Context, req UpdateRequest) (*UpdateResult, error) {
	containerID := req.ContainerID
	newImage := req.NewImage

	h.log.WithFields(logrus.Fields{
		"container_id": safeShortID(containerID),
		"new_image":    newImage,
	}).Info("Starting container update")

	// Convert registry auth
	var registryAuth *update.RegistryAuth
	if req.RegistryAuth != nil {
		registryAuth = &update.RegistryAuth{
			Username: req.RegistryAuth.Username,
			Password: req.RegistryAuth.Password,
		}
	}

	// Create request for shared package
	updateReq := update.UpdateRequest{
		ContainerID:   containerID,
		NewImage:      newImage,
		StopTimeout:   req.StopTimeout,
		HealthTimeout: req.HealthTimeout,
		RegistryAuth:  registryAuth,
	}

	// Re-detect options with callbacks for this specific update
	options := update.DetectOptions(ctx, h.dockerClient.RawClient(), h.log)
	options.OnProgress = func(event update.ProgressEvent) {
		h.sendProgress(containerID, event.Stage, event.Message)
	}
	options.OnPullProgress = func(event update.PullProgressEvent) {
		h.sendLayerProgress(event)
	}

	// Create updater with callbacks
	updater := update.NewUpdater(h.dockerClient.RawClient(), h.log, options)

	// Execute update
	result := updater.Update(ctx, updateReq)

	if !result.Success {
		// Send error event
		if result.RolledBack {
			h.sendProgress(containerID, update.StageRollback, result.Error)
		} else {
			h.sendProgress(containerID, update.StageFailed, result.Error)
		}
		return nil, &UpdateError{Message: result.Error}
	}

	// Send completion event
	completionPayload := map[string]interface{}{
		"old_container_id": result.OldContainerID,
		"new_container_id": result.NewContainerID,
		"container_name":   result.ContainerName,
	}
	if len(result.FailedDependents) > 0 {
		completionPayload["failed_dependents"] = result.FailedDependents
	}
	h.sendEvent("update_complete", completionPayload)

	h.log.WithFields(logrus.Fields{
		"old_container": result.OldContainerID,
		"new_container": result.NewContainerID,
		"name":          result.ContainerName,
	}).Info("Container update completed successfully")

	return &UpdateResult{
		OldContainerID:   result.OldContainerID,
		NewContainerID:   result.NewContainerID,
		ContainerName:    result.ContainerName,
		FailedDependents: result.FailedDependents,
	}, nil
}

// UpdateError is returned when an update fails
type UpdateError struct {
	Message string
}

func (e *UpdateError) Error() string {
	return e.Message
}

// sendProgress sends an update progress event to the backend.
func (h *UpdateHandler) sendProgress(containerID, stage, message string) {
	progress := map[string]interface{}{
		"container_id": safeShortID(containerID),
		"stage":        stage,
		"message":      message,
	}

	if err := h.sendEvent("update_progress", progress); err != nil {
		h.log.WithError(err).Warn("Failed to send update progress")
	}
}

// sendLayerProgress sends layer-by-layer pull progress to the backend.
func (h *UpdateHandler) sendLayerProgress(event update.PullProgressEvent) {
	// Build layer list for frontend (match Python format)
	layerList := make([]map[string]interface{}, 0, len(event.Layers))
	for _, layer := range event.Layers {
		layerList = append(layerList, map[string]interface{}{
			"id":      layer.ID,
			"status":  layer.Status,
			"current": layer.Current,
			"total":   layer.Total,
			"percent": layer.Percent,
		})
	}

	progress := map[string]interface{}{
		"container_id":     safeShortID(event.ContainerID),
		"overall_progress": event.OverallProgress,
		"layers":           layerList,
		"total_layers":     event.TotalLayers,
		"remaining_layers": 0,
		"summary":          event.Summary,
		"speed_mbps":       event.SpeedMbps,
	}

	if err := h.sendEvent("update_layer_progress", progress); err != nil {
		h.log.WithError(err).Debug("Failed to send layer progress")
	}
}
