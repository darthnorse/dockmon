package update

import (
	"bufio"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/api/types/registry"
	"github.com/docker/docker/client"
	"github.com/sirupsen/logrus"
)

// Updater performs container updates using the shared update logic.
type Updater struct {
	cli     *client.Client
	log     *logrus.Logger
	options UpdaterOptions
}

// NewUpdater creates a new Updater with the given options.
func NewUpdater(cli *client.Client, log *logrus.Logger, options UpdaterOptions) *Updater {
	return &Updater{
		cli:     cli,
		log:     log,
		options: options,
	}
}

// Update performs a rolling update of a container.
// Returns the update result with old/new container IDs.
func (u *Updater) Update(ctx context.Context, req UpdateRequest) *UpdateResult {
	containerID := req.ContainerID
	newImage := req.NewImage

	u.log.WithFields(logrus.Fields{
		"container_id": truncateID(containerID),
		"new_image":    newImage,
	}).Info("Starting container update")

	// Default timeouts
	if req.StopTimeout == 0 {
		req.StopTimeout = 30
	}
	if req.HealthTimeout == 0 {
		req.HealthTimeout = 120
	}

	// Step 1: Pull new image with layer progress
	u.sendProgress(StagePulling, fmt.Sprintf("Pulling image %s", newImage))

	if err := u.pullImageWithProgress(ctx, req); err != nil {
		return u.failResult(containerID, StagePulling, err)
	}

	// Step 2: Inspect container to get configuration
	u.sendProgress(StageConfiguring, "Reading container configuration")
	oldContainer, err := u.cli.ContainerInspect(ctx, containerID)
	if err != nil {
		return u.failResult(containerID, StageConfiguring, fmt.Errorf("failed to inspect container: %w", err))
	}

	// Capture original running state to restore after update
	// See: https://github.com/darthnorse/dockmon/issues/90
	wasRunning := oldContainer.State.Running

	// Step 3: Get image labels for label filtering
	oldImageLabels, err := GetImageLabels(ctx, u.cli, oldContainer.Image)
	if err != nil {
		u.log.WithError(err).Warn("Failed to get old image labels, continuing without label filtering")
		oldImageLabels = make(map[string]string)
	}

	newImageLabels, err := GetImageLabels(ctx, u.cli, newImage)
	if err != nil {
		u.log.WithError(err).Warn("Failed to get new image labels, continuing without label filtering")
		newImageLabels = make(map[string]string)
	}

	// Step 4: Find dependent containers BEFORE we stop the parent
	containerName := strings.TrimPrefix(oldContainer.Name, "/")
	dependentContainers, err := FindDependentContainers(ctx, u.cli, u.log, &oldContainer, containerName, containerID)
	if err != nil {
		u.log.WithError(err).Warn("Failed to find dependent containers, continuing")
	}
	if len(dependentContainers) > 0 {
		u.log.Infof("Found %d dependent container(s) using network_mode: container:%s",
			len(dependentContainers), containerName)
	}

	// Step 5: Extract and transform config using struct copy
	extractedConfig, err := ExtractConfig(ctx, u.cli, u.log, &oldContainer, newImage, oldImageLabels, newImageLabels, u.options.IsPodman)
	if err != nil {
		return u.failResult(containerID, StageConfiguring, err)
	}

	// Step 6: Create backup (stop + rename)
	u.sendProgress(StageBackup, "Stopping container and creating backup")
	backupName, err := CreateBackup(ctx, u.cli, u.log, containerID, containerName, req.StopTimeout)
	if err != nil {
		return u.failResult(containerID, StageBackup, err)
	}

	// Step 7: Create new container with original name
	u.sendProgress(StageCreating, "Creating new container")

	var createNetworkConfig *network.NetworkingConfig
	if u.options.SupportsNetworkingConfig {
		// API >= 1.44: Can set static IP at creation
		createNetworkConfig = extractedConfig.NetworkingConfig
		u.log.Debug("Using networking_config at creation (API >= 1.44)")
	} else {
		// API < 1.44: Must connect primary network manually post-creation
		createNetworkConfig = nil
		if extractedConfig.NetworkingConfig != nil {
			u.log.Debug("Will manually connect primary network post-creation (API < 1.44)")
		}
	}

	newContainerResp, err := u.cli.ContainerCreate(
		ctx,
		extractedConfig.Config,
		extractedConfig.HostConfig,
		createNetworkConfig,
		nil,
		containerName,
	)
	if err != nil {
		RestoreBackup(ctx, u.cli, u.log, backupName, containerName)
		return u.failResult(containerID, StageCreating, fmt.Errorf("failed to create container: %w", err))
	}
	newContainerID := newContainerResp.ID

	u.log.Infof("Created new container %s", truncateID(newContainerID))

	// Step 7b: Connect networks post-creation
	// For API < 1.44: Connect primary network with static IP/aliases
	// For all APIs: Connect additional networks (multi-network support)
	if !u.options.SupportsNetworkingConfig && extractedConfig.NetworkingConfig != nil {
		// Legacy API: manually connect primary network
		for networkName, endpointConfig := range extractedConfig.NetworkingConfig.EndpointsConfig {
			u.log.Debugf("Connecting primary network (legacy API): %s", networkName)
			if err := u.cli.NetworkConnect(ctx, networkName, newContainerID, endpointConfig); err != nil {
				// Primary network failure is critical - rollback
				u.log.WithError(err).Errorf("Failed to connect primary network %s", networkName)
				u.cli.ContainerRemove(ctx, newContainerID, container.RemoveOptions{Force: true})
				RestoreBackup(ctx, u.cli, u.log, backupName, containerName)
				return u.failResult(containerID, StageCreating, fmt.Errorf("failed to connect primary network: %w", err))
			}
		}
	}

	// Connect additional networks (always needed for multi-network containers)
	if len(extractedConfig.AdditionalNets) > 0 {
		for networkName, endpointConfig := range extractedConfig.AdditionalNets {
			u.log.Debugf("Connecting to additional network: %s", networkName)
			if err := u.cli.NetworkConnect(ctx, networkName, newContainerID, endpointConfig); err != nil {
				u.log.WithError(err).Warnf("Failed to connect to network %s (continuing)", networkName)
			}
		}
	}

	// Step 8: Start new container
	u.sendProgress(StageStarting, "Starting new container")
	if err := u.cli.ContainerStart(ctx, newContainerID, container.StartOptions{}); err != nil {
		u.cli.ContainerRemove(ctx, newContainerID, container.RemoveOptions{Force: true})
		RestoreBackup(ctx, u.cli, u.log, backupName, containerName)
		return u.failResult(containerID, StageStarting, fmt.Errorf("failed to start container: %w", err))
	}

	// Step 9: Health check
	u.sendProgress(StageHealthCheck, "Waiting for container to be healthy")
	if err := WaitForHealthy(ctx, u.cli, u.log, newContainerID, req.HealthTimeout); err != nil {
		u.log.WithError(err).Warn("Health check failed, rolling back")
		stopTimeout := req.StopTimeout
		u.cli.ContainerStop(ctx, newContainerID, container.StopOptions{Timeout: &stopTimeout})
		u.cli.ContainerRemove(ctx, newContainerID, container.RemoveOptions{Force: true})
		RestoreBackup(ctx, u.cli, u.log, backupName, containerName)
		return u.failResultRolledBack(containerID, StageHealthCheck, fmt.Errorf("health check failed: %w", err))
	}

	// Step 10: Restore original stopped state if container wasn't running before update
	// This ensures stopped containers remain stopped after update (Issue #90)
	if !wasRunning {
		u.log.Info("Container was stopped before update, restoring stopped state")
		stopTimeout := req.StopTimeout
		if err := u.cli.ContainerStop(ctx, newContainerID, container.StopOptions{Timeout: &stopTimeout}); err != nil {
			u.log.WithError(err).Warn("Failed to stop container after update (was originally stopped)")
			// Continue anyway - update succeeded, just state restoration failed
		}
	}

	// Step 11: Recreate dependent containers with new parent ID
	var failedDeps []string
	if len(dependentContainers) > 0 {
		u.sendProgress(StageDependents,
			fmt.Sprintf("Recreating %d dependent container(s)", len(dependentContainers)))

		failedDeps = RecreateDependentContainers(ctx, u.cli, u.log, dependentContainers, newContainerID, req.StopTimeout, u.options.IsPodman)
		if len(failedDeps) > 0 {
			u.log.Warnf("Failed to recreate dependent containers: %v", failedDeps)
			// Note: We continue despite failures - main container update succeeded
		}
	}

	// Step 12: Cleanup backup (success path)
	u.sendProgress(StageCleanup, "Removing backup container")
	RemoveBackup(ctx, u.cli, u.log, backupName)

	// Success!
	result := &UpdateResult{
		Success:          true,
		OldContainerID:   truncateID(containerID),
		NewContainerID:   truncateID(newContainerID),
		ContainerName:    containerName,
		FailedDependents: failedDeps,
	}

	u.sendProgress(StageCompleted, fmt.Sprintf("Update complete, new container: %s", truncateID(newContainerID)))

	u.log.WithFields(logrus.Fields{
		"old_container": truncateID(containerID),
		"new_container": truncateID(newContainerID),
		"name":          containerName,
	}).Info("Container update completed successfully")

	return result
}

// pullImageWithProgress pulls a Docker image with layer progress reporting.
func (u *Updater) pullImageWithProgress(ctx context.Context, req UpdateRequest) error {
	pullOpts := image.PullOptions{}
	if req.RegistryAuth != nil && req.RegistryAuth.Username != "" {
		authConfig := registry.AuthConfig{
			Username: req.RegistryAuth.Username,
			Password: req.RegistryAuth.Password,
		}
		encodedJSON, err := json.Marshal(authConfig)
		if err == nil {
			pullOpts.RegistryAuth = base64.URLEncoding.EncodeToString(encodedJSON)
			u.log.Debug("Using registry authentication for image pull")
		}
	}

	reader, err := u.cli.ImagePull(ctx, req.NewImage, pullOpts)
	if err != nil {
		return fmt.Errorf("failed to pull image: %w", err)
	}
	defer reader.Close()

	// Track layer progress state for aggregation
	layerStatus := make(map[string]*LayerProgress)
	var lastBroadcast time.Time
	var lastPercent int

	// Speed calculation state
	lastSpeedCheck := time.Now()
	var lastTotalBytes int64
	var speedSamples []float64
	var currentSpeedMbps float64

	// Parse JSON lines from the progress stream
	scanner := bufio.NewScanner(reader)
	buf := make([]byte, 64*1024)
	scanner.Buffer(buf, 1024*1024)

	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}

		var progress struct {
			ID             string `json:"id"`
			Status         string `json:"status"`
			ProgressDetail struct {
				Current int64 `json:"current"`
				Total   int64 `json:"total"`
			} `json:"progressDetail"`
		}

		if err := json.Unmarshal(line, &progress); err != nil {
			continue
		}

		if progress.ID == "" {
			continue
		}

		layer, exists := layerStatus[progress.ID]
		if !exists {
			layer = &LayerProgress{}
			layerStatus[progress.ID] = layer
		}

		layer.ID = progress.ID
		layer.Status = progress.Status

		// Handle completion events specially
		if progress.Status == "Pull complete" || progress.Status == "Already exists" {
			layer.Current = layer.Total
		} else {
			layer.Current = progress.ProgressDetail.Current
			if progress.ProgressDetail.Total > 0 {
				layer.Total = progress.ProgressDetail.Total
			}
		}

		// Calculate percent for this layer
		if layer.Total > 0 {
			layer.Percent = int((layer.Current * 100) / layer.Total)
		}

		// Calculate overall progress
		var totalBytes, downloadedBytes int64
		for _, l := range layerStatus {
			if l.Total > 0 {
				totalBytes += l.Total
				downloadedBytes += l.Current
			}
		}

		overallPercent := 0
		if totalBytes > 0 {
			overallPercent = int((downloadedBytes * 100) / totalBytes)
		}

		// Calculate download speed (MB/s) with moving average smoothing
		now := time.Now()
		timeDelta := now.Sub(lastSpeedCheck).Seconds()

		if timeDelta >= 1.0 {
			bytesDelta := downloadedBytes - lastTotalBytes
			if bytesDelta > 0 {
				rawSpeed := float64(bytesDelta) / timeDelta / (1024 * 1024)
				speedSamples = append(speedSamples, rawSpeed)
				if len(speedSamples) > 3 {
					speedSamples = speedSamples[1:]
				}

				var sum float64
				for _, s := range speedSamples {
					sum += s
				}
				currentSpeedMbps = sum / float64(len(speedSamples))
			}

			lastTotalBytes = downloadedBytes
			lastSpeedCheck = now
		}

		// Throttle broadcasts: every 500ms OR 5% change OR completion events
		isCompletion := strings.Contains(strings.ToLower(progress.Status), "complete") ||
			progress.Status == "Already exists"
		shouldBroadcast := now.Sub(lastBroadcast) >= 500*time.Millisecond ||
			abs(overallPercent-lastPercent) >= 5 ||
			isCompletion

		if shouldBroadcast && u.options.OnPullProgress != nil {
			u.sendPullProgress(req.ContainerID, layerStatus, overallPercent, currentSpeedMbps)
			lastBroadcast = now
			lastPercent = overallPercent
		}
	}

	return nil
}

// sendPullProgress sends detailed layer progress.
func (u *Updater) sendPullProgress(containerID string, layers map[string]*LayerProgress, overallPercent int, speedMbps float64) {
	if u.options.OnPullProgress == nil {
		return
	}

	// Build layer list with status counts
	layerList := make([]*LayerProgress, 0, len(layers))
	var downloading, extracting, complete, cached int

	for _, layer := range layers {
		layerList = append(layerList, layer)

		switch layer.Status {
		case "Downloading":
			downloading++
		case "Extracting":
			extracting++
		case "Already exists":
			cached++
		case "Pull complete", "Download complete":
			complete++
		}
	}

	// Sort layers by priority (active layers first) for consistent display
	// Priority: Downloading > Extracting > Waiting > Pull complete > Already exists
	sortLayersByPriority(layerList)

	// Truncate to 20 layers for network efficiency (matches Python behavior)
	// UI only displays top 15, so sending all 50+ layers is wasteful
	totalLayers := len(layerList)
	remainingLayers := 0
	if len(layerList) > 20 {
		remainingLayers = len(layerList) - 20
		layerList = layerList[:20]
	}

	// Build summary message
	var summary string
	if downloading > 0 {
		summary = fmt.Sprintf("Downloading %d of %d layers (%d%%)", downloading, totalLayers, overallPercent)
	} else if extracting > 0 {
		summary = fmt.Sprintf("Extracting %d of %d layers (%d%%)", extracting, totalLayers, overallPercent)
	} else if complete+cached == totalLayers && totalLayers > 0 {
		if cached > 0 {
			summary = fmt.Sprintf("Pull complete (%d layers, %d cached)", totalLayers, cached)
		} else {
			summary = fmt.Sprintf("Pull complete (%d layers)", totalLayers)
		}
	} else {
		summary = fmt.Sprintf("Pulling image (%d%%)", overallPercent)
	}

	u.options.OnPullProgress(PullProgressEvent{
		ContainerID:     truncateID(containerID),
		OverallProgress: overallPercent,
		Layers:          layerList,
		TotalLayers:     totalLayers,
		RemainingLayers: remainingLayers,
		Summary:         summary,
		SpeedMbps:       speedMbps,
	})
}

// sortLayersByPriority sorts layers by status priority (active layers first).
func sortLayersByPriority(layers []*LayerProgress) {
	priorityMap := map[string]int{
		"Downloading":       0,
		"Extracting":        1,
		"Verifying Checksum": 2,
		"Download complete":  3,
		"Pull complete":      4,
		"Already exists":     5,
		"Waiting":            6,
		"Pulling fs layer":   7,
	}

	// Simple insertion sort (typically < 50 layers)
	for i := 1; i < len(layers); i++ {
		j := i
		for j > 0 {
			pi := priorityMap[layers[j-1].Status]
			pj := priorityMap[layers[j].Status]
			// Use 99 for unknown statuses to sort them last
			if pi == 0 && layers[j-1].Status != "Downloading" {
				pi = 99
			}
			if pj == 0 && layers[j].Status != "Downloading" {
				pj = 99
			}
			if pi <= pj {
				break
			}
			layers[j-1], layers[j] = layers[j], layers[j-1]
			j--
		}
	}
}

// sendProgress sends a progress event if callback is registered.
func (u *Updater) sendProgress(stage, message string) {
	if u.options.OnProgress != nil {
		u.options.OnProgress(ProgressEvent{
			Stage:   stage,
			Message: message,
		})
	}
}

// failResult creates a failed result.
func (u *Updater) failResult(containerID, stage string, err error) *UpdateResult {
	u.sendProgress(StageFailed, err.Error())

	return &UpdateResult{
		Success:        false,
		OldContainerID: truncateID(containerID),
		Error:          err.Error(),
	}
}

// failResultRolledBack creates a failed result with rollback indicator.
func (u *Updater) failResultRolledBack(containerID, stage string, err error) *UpdateResult {
	u.sendProgress(StageRollback, err.Error())

	return &UpdateResult{
		Success:        false,
		OldContainerID: truncateID(containerID),
		RolledBack:     true,
		Error:          err.Error(),
	}
}

// abs returns the absolute value of an integer.
func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
