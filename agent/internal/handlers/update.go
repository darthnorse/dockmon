package handlers

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/docker"
	dockerTypes "github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/network"
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

// UpdateHandler manages container updates using struct-copy passthrough
type UpdateHandler struct {
	dockerClient             *docker.Client
	log                      *logrus.Logger
	sendEvent                func(msgType string, payload interface{}) error
	isPodman                 bool // Detected at init, cached
	supportsNetworkingConfig bool // API >= 1.44, detected at init, cached
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
	OldContainerID string `json:"old_container_id"`
	NewContainerID string `json:"new_container_id"`
	ContainerName  string `json:"container_name"`
}

// DependentContainer holds info about a container that depends on another
// via network_mode: container:X
type DependentContainer struct {
	Container      dockerTypes.ContainerJSON
	Name           string
	ID             string
	Image          string
	OldNetworkMode string
}

// ExtractedConfig holds the extracted container configuration.
// Mirrors Python's extracted_config dict structure.
type ExtractedConfig struct {
	Config           *container.Config
	HostConfig       *container.HostConfig
	NetworkingConfig *network.NetworkingConfig
	AdditionalNets   map[string]*network.EndpointSettings
	ContainerName    string
}

// UpdateProgress stages (aligned with Python backend)
const (
	StagePulling     = "pulling"
	StageConfiguring = "configuring"
	StageBackup      = "backup"
	StageCreating    = "creating"
	StageStarting    = "starting"
	StageHealthCheck = "health_check"
	StageDependents  = "dependents" // For dependent container recreation
	StageCleanup     = "cleanup"
	StageCompleted   = "completed"
)

// layerProgress tracks progress for a single image layer
type layerProgress struct {
	ID      string `json:"id"`
	Status  string `json:"status"`
	Current int64  `json:"current"`
	Total   int64  `json:"total"`
}

// abs returns the absolute value of an integer
func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}

// NewUpdateHandler creates a new update handler with runtime detection.
// Detects Podman and Docker API version at initialization for efficiency.
func NewUpdateHandler(
	ctx context.Context,
	dockerClient *docker.Client,
	log *logrus.Logger,
	sendEvent func(string, interface{}) error,
) (*UpdateHandler, error) {
	// Detect Podman
	isPodman, err := dockerClient.IsPodman(ctx)
	if err != nil {
		log.WithError(err).Warn("Failed to detect Podman, assuming Docker")
		isPodman = false
	}

	if isPodman {
		log.Info("Detected Podman runtime - will apply compatibility fixes")
	}

	// Detect API version for networking_config support
	supportsNetworkingConfig, err := dockerClient.SupportsNetworkingConfig(ctx)
	if err != nil {
		log.WithError(err).Warn("Failed to detect API version, assuming legacy mode")
		supportsNetworkingConfig = false
	}

	apiVersion, _ := dockerClient.GetAPIVersion(ctx)
	if supportsNetworkingConfig {
		log.Infof("Docker API %s supports networking_config at creation", apiVersion)
	} else {
		log.Infof("Docker API %s requires manual network connection (legacy mode)", apiVersion)
	}

	return &UpdateHandler{
		dockerClient:             dockerClient,
		log:                      log,
		sendEvent:                sendEvent,
		isPodman:                 isPodman,
		supportsNetworkingConfig: supportsNetworkingConfig,
	}, nil
}

// UpdateContainer performs a rolling update of a container using struct-copy passthrough.
// Returns the update result with old/new container IDs.
func (h *UpdateHandler) UpdateContainer(ctx context.Context, req UpdateRequest) (*UpdateResult, error) {
	containerID := req.ContainerID
	newImage := req.NewImage

	h.log.WithFields(logrus.Fields{
		"container_id": safeShortID(containerID),
		"new_image":    newImage,
	}).Info("Starting container update")

	// Default timeouts (match Python defaults from GlobalSettings)
	if req.StopTimeout == 0 {
		req.StopTimeout = 30
	}
	if req.HealthTimeout == 0 {
		req.HealthTimeout = 120 // Match Python default
	}

	// Step 1: Pull new image with layer progress
	h.sendProgress(containerID, StagePulling, fmt.Sprintf("Pulling image %s", newImage))

	// Convert registry auth from handlers to docker package type
	var dockerAuth *docker.RegistryAuth
	if req.RegistryAuth != nil {
		dockerAuth = &docker.RegistryAuth{
			Username: req.RegistryAuth.Username,
			Password: req.RegistryAuth.Password,
		}
	}

	// Track layer progress state for aggregation
	layerStatus := make(map[string]*layerProgress)
	var lastBroadcast time.Time
	var lastPercent int

	// Speed calculation state (matches Python implementation)
	lastSpeedCheck := time.Now()
	var lastTotalBytes int64
	var speedSamples []float64
	var currentSpeedMbps float64

	err := h.dockerClient.PullImageWithProgress(ctx, newImage, dockerAuth, func(progress docker.PullProgress) {
		// Update layer tracking
		if progress.ID == "" {
			return // Skip non-layer messages
		}

		layer, exists := layerStatus[progress.ID]
		if !exists {
			layer = &layerProgress{}
			layerStatus[progress.ID] = layer
		}

		layer.ID = progress.ID
		layer.Status = progress.Status

		// Handle completion events specially - Docker sends empty ProgressDetail
		// for "Pull complete" and "Already exists", which would reset Current to 0
		// and break the overall progress calculation (matches Python implementation)
		if progress.Status == "Pull complete" || progress.Status == "Already exists" {
			// Mark as fully downloaded by setting current = total
			layer.Current = layer.Total
		} else {
			layer.Current = progress.ProgressDetail.Current
			if progress.ProgressDetail.Total > 0 {
				layer.Total = progress.ProgressDetail.Total
			}
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
		// Matches Python implementation in image_pull_progress.py
		now := time.Now()
		timeDelta := now.Sub(lastSpeedCheck).Seconds()

		if timeDelta >= 1.0 { // Update speed every second
			bytesDelta := downloadedBytes - lastTotalBytes
			if bytesDelta > 0 {
				// Calculate raw speed in MB/s
				rawSpeed := float64(bytesDelta) / timeDelta / (1024 * 1024)

				// Apply 3-sample moving average to smooth jitter
				speedSamples = append(speedSamples, rawSpeed)
				if len(speedSamples) > 3 {
					speedSamples = speedSamples[1:] // Remove oldest sample
				}

				// Calculate smoothed average
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

		if shouldBroadcast {
			h.sendLayerProgress(containerID, layerStatus, overallPercent, currentSpeedMbps)
			lastBroadcast = now
			lastPercent = overallPercent
		}
	})

	if err != nil {
		return nil, h.fail(containerID, StagePulling, fmt.Errorf("failed to pull image: %w", err))
	}

	// Step 2: Inspect container to get configuration
	h.sendProgress(containerID, StageConfiguring, "Reading container configuration")
	oldContainer, err := h.dockerClient.InspectContainer(ctx, containerID)
	if err != nil {
		return nil, h.fail(containerID, StageConfiguring, fmt.Errorf("failed to inspect container: %w", err))
	}

	// Step 3: Get image labels for label filtering
	oldImageLabels, err := h.dockerClient.GetImageLabels(ctx, oldContainer.Image)
	if err != nil {
		h.log.WithError(err).Warn("Failed to get old image labels, continuing without label filtering")
		oldImageLabels = make(map[string]string)
	}

	newImageLabels, err := h.dockerClient.GetImageLabels(ctx, newImage)
	if err != nil {
		h.log.WithError(err).Warn("Failed to get new image labels, continuing without label filtering")
		newImageLabels = make(map[string]string)
	}

	// Step 4: Find dependent containers BEFORE we stop the parent
	containerName := strings.TrimPrefix(oldContainer.Name, "/")
	dependentContainers, err := h.findDependentContainers(ctx, &oldContainer, containerName, containerID)
	if err != nil {
		h.log.WithError(err).Warn("Failed to find dependent containers, continuing")
	}
	if len(dependentContainers) > 0 {
		h.log.Infof("Found %d dependent container(s) using network_mode: container:%s",
			len(dependentContainers), containerName)
	}

	// Step 5: Extract and transform config using struct copy
	extractedConfig, err := h.extractConfig(&oldContainer, newImage, oldImageLabels, newImageLabels)
	if err != nil {
		return nil, h.fail(containerID, StageConfiguring, err)
	}

	// Step 6: Create backup (stop + rename)
	h.sendProgress(containerID, StageBackup, "Stopping container and creating backup")
	backupName, err := h.createBackup(ctx, containerID, containerName, req.StopTimeout)
	if err != nil {
		return nil, h.fail(containerID, StageBackup, err)
	}

	// Step 7: Create new container with original name
	h.sendProgress(containerID, StageCreating, "Creating new container")

	var createNetworkConfig *network.NetworkingConfig
	if h.supportsNetworkingConfig {
		// API >= 1.44: Can set static IP at creation
		createNetworkConfig = extractedConfig.NetworkingConfig
		h.log.Debug("Using networking_config at creation (API >= 1.44)")
	} else {
		// API < 1.44: Must connect primary network manually post-creation
		createNetworkConfig = nil
		if extractedConfig.NetworkingConfig != nil {
			h.log.Debug("Will manually connect primary network post-creation (API < 1.44)")
		}
	}

	newContainerID, err := h.dockerClient.CreateContainerWithNetwork(
		ctx,
		extractedConfig.Config,
		extractedConfig.HostConfig,
		createNetworkConfig,
		containerName,
	)
	if err != nil {
		h.restoreBackup(ctx, backupName, containerName)
		return nil, h.fail(containerID, StageCreating, fmt.Errorf("failed to create container: %w", err))
	}

	h.log.Infof("Created new container %s", safeShortID(newContainerID))

	// Step 7b: Connect networks post-creation
	// For API < 1.44: Connect primary network with static IP/aliases
	// For all APIs: Connect additional networks (multi-network support)
	if !h.supportsNetworkingConfig && extractedConfig.NetworkingConfig != nil {
		// Legacy API: manually connect primary network
		for networkName, endpointConfig := range extractedConfig.NetworkingConfig.EndpointsConfig {
			h.log.Debugf("Connecting primary network (legacy API): %s", networkName)
			if err := h.dockerClient.ConnectNetwork(ctx, newContainerID, networkName, endpointConfig); err != nil {
				// Primary network failure is critical - rollback
				h.log.WithError(err).Errorf("Failed to connect primary network %s", networkName)
				h.dockerClient.RemoveContainer(ctx, newContainerID, true)
				h.restoreBackup(ctx, backupName, containerName)
				return nil, h.fail(containerID, StageCreating, fmt.Errorf("failed to connect primary network: %w", err))
			}
		}
	}

	// Connect additional networks (always needed for multi-network containers)
	if len(extractedConfig.AdditionalNets) > 0 {
		for networkName, endpointConfig := range extractedConfig.AdditionalNets {
			h.log.Debugf("Connecting to additional network: %s", networkName)
			if err := h.dockerClient.ConnectNetwork(ctx, newContainerID, networkName, endpointConfig); err != nil {
				h.log.WithError(err).Warnf("Failed to connect to network %s (continuing)", networkName)
			}
		}
	}

	// Step 8: Start new container
	h.sendProgress(containerID, StageStarting, "Starting new container")
	if err := h.dockerClient.StartContainer(ctx, newContainerID); err != nil {
		h.dockerClient.RemoveContainer(ctx, newContainerID, true)
		h.restoreBackup(ctx, backupName, containerName)
		return nil, h.fail(containerID, StageStarting, fmt.Errorf("failed to start container: %w", err))
	}

	// Step 9: Health check
	h.sendProgress(containerID, StageHealthCheck, "Waiting for container to be healthy")
	if err := h.waitForHealthy(ctx, newContainerID, req.HealthTimeout); err != nil {
		h.log.WithError(err).Warn("Health check failed, rolling back")
		h.dockerClient.StopContainer(ctx, newContainerID, req.StopTimeout)
		h.dockerClient.RemoveContainer(ctx, newContainerID, true)
		h.restoreBackup(ctx, backupName, containerName)
		return nil, h.fail(containerID, StageHealthCheck, fmt.Errorf("health check failed: %w", err))
	}

	// Step 10: Recreate dependent containers with new parent ID
	var failedDeps []string
	if len(dependentContainers) > 0 {
		h.sendProgress(containerID, StageDependents,
			fmt.Sprintf("Recreating %d dependent container(s)", len(dependentContainers)))

		failedDeps = h.recreateDependentContainers(ctx, dependentContainers, newContainerID, req.StopTimeout)
		if len(failedDeps) > 0 {
			h.log.Warnf("Failed to recreate dependent containers: %v", failedDeps)
			// Note: We continue despite failures - main container update succeeded
		}
	}

	// Step 11: Cleanup backup (success path)
	h.sendProgress(containerID, StageCleanup, "Removing backup container")
	h.removeBackup(ctx, backupName)

	// Success!
	result := &UpdateResult{
		OldContainerID: safeShortID(containerID),
		NewContainerID: safeShortID(newContainerID),
		ContainerName:  containerName,
	}

	h.sendProgress(containerID, StageCompleted, fmt.Sprintf("Update complete, new container: %s", safeShortID(newContainerID)))

	// Send completion event with new container ID for database update
	completionPayload := map[string]interface{}{
		"old_container_id": safeShortID(containerID),
		"new_container_id": safeShortID(newContainerID),
		"container_name":   containerName,
	}
	if len(failedDeps) > 0 {
		completionPayload["failed_dependents"] = failedDeps
	}
	h.sendEvent("update_complete", completionPayload)

	h.log.WithFields(logrus.Fields{
		"old_container": safeShortID(containerID),
		"new_container": safeShortID(newContainerID),
		"name":          containerName,
	}).Info("Container update completed successfully")

	return result, nil
}

// extractConfig extracts container configuration using struct-copy passthrough.
//
// SHALLOW COPY SAFETY NOTE:
// Go struct copy (`newHostConfig := *inspect.HostConfig`) creates a shallow copy where
// pointer fields (slices, maps, nested structs) point to the same underlying data.
// This is SAFE because:
// 1. We do NOT modify the original config after copying
// 2. The original container is being destroyed anyway
// 3. We only REPLACE pointer fields, never mutate their contents
func (h *UpdateHandler) extractConfig(
	inspect *dockerTypes.ContainerJSON,
	newImage string,
	oldImageLabels map[string]string,
	newImageLabels map[string]string,
) (*ExtractedConfig, error) {

	// STRUCT COPY - preserves ALL fields including DeviceRequests, Healthcheck, Tmpfs, etc.
	newConfig := *inspect.Config
	newConfig.Image = newImage

	// STRUCT COPY - preserves ALL fields including DeviceRequests, Resources, etc.
	newHostConfig := *inspect.HostConfig

	// Apply Podman compatibility fixes
	if h.isPodman {
		h.applyPodmanFixes(&newHostConfig)
	}

	// Handle hostname/mac for container:X network mode
	networkMode := string(newHostConfig.NetworkMode)
	if strings.HasPrefix(networkMode, "container:") {
		newConfig.Hostname = ""
		newConfig.Domainname = ""
		newConfig.MacAddress = ""
		h.log.Debug("Cleared Hostname/Domainname/MacAddress for container: network mode")
	}

	// Resolve NetworkMode container:ID -> container:name
	if err := h.resolveNetworkMode(&newHostConfig); err != nil {
		h.log.WithError(err).Warn("Failed to resolve NetworkMode, using as-is")
	}

	// Extract user-added labels (filter out old image labels)
	userLabels := h.extractUserLabels(newConfig.Labels, oldImageLabels)
	newConfig.Labels = userLabels

	// Extract network configuration
	primaryNetConfig, additionalNetworks := h.extractNetworkConfig(inspect)

	containerName := strings.TrimPrefix(inspect.Name, "/")

	return &ExtractedConfig{
		Config:           &newConfig,
		HostConfig:       &newHostConfig,
		NetworkingConfig: primaryNetConfig,
		AdditionalNets:   additionalNetworks,
		ContainerName:    containerName,
	}, nil
}

// extractUserLabels filters container labels to preserve only user-added labels.
// Removes labels that came from the OLD image so new image labels can take effect.
func (h *UpdateHandler) extractUserLabels(
	containerLabels map[string]string,
	oldImageLabels map[string]string,
) map[string]string {
	if containerLabels == nil {
		return make(map[string]string)
	}

	userLabels := make(map[string]string)
	for key, containerValue := range containerLabels {
		// Keep label if:
		// 1. It doesn't exist in old image labels (user added it), OR
		// 2. Its value differs from old image (user modified it)
		imageValue, existsInImage := oldImageLabels[key]
		if !existsInImage || containerValue != imageValue {
			userLabels[key] = containerValue
		}
	}

	h.log.Debugf("Label filtering: %d container - %d image defaults = %d user labels preserved",
		len(containerLabels), len(oldImageLabels), len(userLabels))

	return userLabels
}

// applyPodmanFixes modifies HostConfig for Podman compatibility.
func (h *UpdateHandler) applyPodmanFixes(hostConfig *container.HostConfig) {
	// Fix 1: NanoCpus -> CpuQuota/CpuPeriod
	if hostConfig.NanoCPUs > 0 && hostConfig.CPUPeriod == 0 {
		cpuPeriod := int64(100000)
		cpuQuota := int64(float64(hostConfig.NanoCPUs) / 1e9 * float64(cpuPeriod))
		hostConfig.CPUPeriod = cpuPeriod
		hostConfig.CPUQuota = cpuQuota
		hostConfig.NanoCPUs = 0
		h.log.Debug("Converted NanoCpus to CpuQuota/CpuPeriod for Podman")
	}

	// Fix 2: Remove MemorySwappiness for Podman
	if hostConfig.Resources.MemorySwappiness != nil {
		hostConfig.Resources.MemorySwappiness = nil
		h.log.Debug("Removed MemorySwappiness for Podman compatibility")
	}
}

// resolveNetworkMode converts container:ID to container:name in NetworkMode.
func (h *UpdateHandler) resolveNetworkMode(hostConfig *container.HostConfig) error {
	networkMode := string(hostConfig.NetworkMode)
	if !strings.HasPrefix(networkMode, "container:") {
		return nil
	}

	refID := strings.TrimPrefix(networkMode, "container:")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	refContainer, err := h.dockerClient.InspectContainer(ctx, refID)
	if err != nil {
		return fmt.Errorf("failed to resolve container reference %s: %w", refID, err)
	}

	refName := strings.TrimPrefix(refContainer.Name, "/")
	hostConfig.NetworkMode = container.NetworkMode("container:" + refName)
	h.log.Debugf("Resolved NetworkMode to container:%s", refName)

	return nil
}

// extractNetworkConfig extracts network configuration from container.
func (h *UpdateHandler) extractNetworkConfig(
	inspect *dockerTypes.ContainerJSON,
) (*network.NetworkingConfig, map[string]*network.EndpointSettings) {

	if inspect.NetworkSettings == nil || inspect.NetworkSettings.Networks == nil {
		return nil, nil
	}

	networks := inspect.NetworkSettings.Networks
	networkMode := string(inspect.HostConfig.NetworkMode)

	// Handle special network modes - no network config needed
	if strings.HasPrefix(networkMode, "container:") || networkMode == "host" || networkMode == "none" {
		return nil, nil
	}

	// Filter to custom networks only (exclude bridge, host, none)
	customNetworks := make(map[string]*network.EndpointSettings)
	for name, data := range networks {
		if name != "bridge" && name != "host" && name != "none" {
			customNetworks[name] = data
		}
	}

	if len(customNetworks) == 0 {
		return nil, nil
	}

	// Determine primary network
	primaryNetwork := networkMode
	if primaryNetwork == "" || primaryNetwork == "default" {
		primaryNetwork = "bridge"
	}
	// If NetworkMode doesn't match a network name, use first custom network
	if _, exists := customNetworks[primaryNetwork]; !exists && len(customNetworks) > 0 {
		for name := range customNetworks {
			primaryNetwork = name
			break
		}
	}

	var primaryNetConfig *network.NetworkingConfig
	additionalNetworks := make(map[string]*network.EndpointSettings)

	for networkName, networkData := range customNetworks {
		endpointConfig := h.buildEndpointConfig(networkData)

		if networkName == primaryNetwork {
			hasConfig := endpointConfig.IPAMConfig != nil ||
				len(endpointConfig.Aliases) > 0 ||
				len(endpointConfig.Links) > 0

			if hasConfig {
				primaryNetConfig = &network.NetworkingConfig{
					EndpointsConfig: map[string]*network.EndpointSettings{
						networkName: endpointConfig,
					},
				}
				h.log.Debugf("Primary network %s has static config (IP/aliases/links)", networkName)
			}
		} else {
			additionalNetworks[networkName] = endpointConfig
		}
	}

	if len(additionalNetworks) == 0 {
		additionalNetworks = nil
	} else {
		h.log.Debugf("Extracted %d additional networks for post-creation connection", len(additionalNetworks))
	}

	return primaryNetConfig, additionalNetworks
}

// buildEndpointConfig creates an EndpointSettings with user-configured values only.
func (h *UpdateHandler) buildEndpointConfig(data *network.EndpointSettings) *network.EndpointSettings {
	endpoint := &network.EndpointSettings{}

	// Extract IPAM config (static IPs)
	if data.IPAMConfig != nil {
		ipam := &network.EndpointIPAMConfig{}
		if data.IPAMConfig.IPv4Address != "" {
			ipam.IPv4Address = data.IPAMConfig.IPv4Address
		}
		if data.IPAMConfig.IPv6Address != "" {
			ipam.IPv6Address = data.IPAMConfig.IPv6Address
		}
		if ipam.IPv4Address != "" || ipam.IPv6Address != "" {
			endpoint.IPAMConfig = ipam
		}
	}

	// Filter aliases - remove auto-generated short ID (12 chars)
	if len(data.Aliases) > 0 {
		var userAliases []string
		for _, alias := range data.Aliases {
			if len(alias) != 12 {
				userAliases = append(userAliases, alias)
			}
		}
		if len(userAliases) > 0 {
			endpoint.Aliases = userAliases
		}
	}

	// Preserve links
	if len(data.Links) > 0 {
		endpoint.Links = data.Links
	}

	return endpoint
}

// findDependentContainers finds all containers that depend on this container
// via network_mode: container:X
func (h *UpdateHandler) findDependentContainers(
	ctx context.Context,
	parentContainer *dockerTypes.ContainerJSON,
	parentName string,
	parentID string,
) ([]DependentContainer, error) {
	var dependents []DependentContainer

	containers, err := h.dockerClient.ListAllContainers(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to list containers: %w", err)
	}

	for _, c := range containers {
		// Skip self
		if c.ID == parentContainer.ID {
			continue
		}

		// Inspect to get full config including NetworkMode
		inspect, err := h.dockerClient.InspectContainer(ctx, c.ID)
		if err != nil {
			h.log.WithError(err).Warnf("Failed to inspect container %s", safeShortID(c.ID))
			continue
		}

		networkMode := string(inspect.HostConfig.NetworkMode)

		// Check if this container depends on our parent
		isDependent := networkMode == fmt.Sprintf("container:%s", parentName) ||
			networkMode == fmt.Sprintf("container:%s", parentID) ||
			networkMode == fmt.Sprintf("container:%s", parentContainer.ID)

		if isDependent {
			imageName := inspect.Config.Image
			if imageName == "" && len(inspect.Image) > 0 {
				imageName = inspect.Image
			}

			depName := strings.TrimPrefix(inspect.Name, "/")
			h.log.Infof("Found dependent container: %s (network_mode: %s)", depName, networkMode)

			dependents = append(dependents, DependentContainer{
				Container:      inspect,
				Name:           depName,
				ID:             safeShortID(inspect.ID),
				Image:          imageName,
				OldNetworkMode: networkMode,
			})
		}
	}

	return dependents, nil
}

// recreateDependentContainers recreates all dependent containers with updated network_mode.
// Returns list of container names that failed to recreate.
func (h *UpdateHandler) recreateDependentContainers(
	ctx context.Context,
	dependents []DependentContainer,
	newParentID string,
	stopTimeout int,
) []string {
	var failed []string

	for _, dep := range dependents {
		if err := h.recreateDependentContainer(ctx, dep, newParentID, stopTimeout); err != nil {
			h.log.WithError(err).Errorf("Failed to recreate dependent container %s", dep.Name)
			failed = append(failed, dep.Name)
		}
	}

	return failed
}

// recreateDependentContainer recreates a single dependent container with updated network_mode.
func (h *UpdateHandler) recreateDependentContainer(
	ctx context.Context,
	dep DependentContainer,
	newParentID string,
	stopTimeout int,
) error {
	h.log.Infof("Recreating dependent container: %s", dep.Name)

	// Get labels for filtering (skip for dependents since we don't have old image labels)
	emptyLabels := make(map[string]string)

	// Extract config from dependent container
	extractedConfig, err := h.extractConfig(&dep.Container, dep.Image, emptyLabels, emptyLabels)
	if err != nil {
		return fmt.Errorf("failed to extract config: %w", err)
	}

	// Update NetworkMode to point to new parent
	oldNetworkMode := string(extractedConfig.HostConfig.NetworkMode)
	extractedConfig.HostConfig.NetworkMode = container.NetworkMode(fmt.Sprintf("container:%s", newParentID))
	h.log.Infof("Updated NetworkMode: %s -> container:%s", oldNetworkMode, safeShortID(newParentID))

	// Stop dependent container
	h.log.Debugf("Stopping dependent container: %s", dep.Name)
	if err := h.dockerClient.StopContainer(ctx, dep.Container.ID, stopTimeout); err != nil {
		// Try kill if stop fails
		h.dockerClient.KillContainer(ctx, dep.Container.ID)
	}

	// Rename to temp name
	tempName := fmt.Sprintf("%s-dockmon-temp-%d", dep.Name, time.Now().Unix())
	if err := h.dockerClient.RenameContainer(ctx, dep.Container.ID, tempName); err != nil {
		return fmt.Errorf("failed to rename to temp: %w", err)
	}

	// Create new dependent container
	newDepID, err := h.dockerClient.CreateContainer(
		ctx,
		extractedConfig.Config,
		extractedConfig.HostConfig,
		dep.Name,
	)
	if err != nil {
		// Rollback: restore temp container
		h.dockerClient.RenameContainer(ctx, dep.Container.ID, dep.Name)
		h.dockerClient.StartContainer(ctx, dep.Container.ID)
		return fmt.Errorf("failed to create new container: %w", err)
	}

	// Connect additional networks
	if len(extractedConfig.AdditionalNets) > 0 {
		for networkName, endpointConfig := range extractedConfig.AdditionalNets {
			h.dockerClient.ConnectNetwork(ctx, newDepID, networkName, endpointConfig)
		}
	}

	// Start new dependent container
	if err := h.dockerClient.StartContainer(ctx, newDepID); err != nil {
		// Rollback
		h.dockerClient.RemoveContainer(ctx, newDepID, true)
		h.dockerClient.RenameContainer(ctx, dep.Container.ID, dep.Name)
		h.dockerClient.StartContainer(ctx, dep.Container.ID)
		return fmt.Errorf("failed to start new container: %w", err)
	}

	// Wait a bit and verify it's running
	time.Sleep(3 * time.Second)
	newInspect, err := h.dockerClient.InspectContainer(ctx, newDepID)
	if err != nil || !newInspect.State.Running {
		// Rollback
		h.dockerClient.StopContainer(ctx, newDepID, 10)
		h.dockerClient.RemoveContainer(ctx, newDepID, true)
		h.dockerClient.RenameContainer(ctx, dep.Container.ID, dep.Name)
		h.dockerClient.StartContainer(ctx, dep.Container.ID)
		return fmt.Errorf("new container failed to start properly")
	}

	// Success - remove old temp container
	tempContainer, _ := h.dockerClient.GetContainerByName(ctx, tempName)
	if tempContainer != "" {
		h.dockerClient.RemoveContainer(ctx, tempContainer, true)
	}

	h.log.Infof("Successfully recreated dependent container: %s (new ID: %s)", dep.Name, safeShortID(newDepID))
	return nil
}

// createBackup stops the container and renames it to a backup name.
func (h *UpdateHandler) createBackup(
	ctx context.Context,
	containerID string,
	containerName string,
	stopTimeout int,
) (string, error) {
	backupName := fmt.Sprintf("%s-dockmon-backup-%d", containerName, time.Now().Unix())

	// Stop container gracefully
	h.log.Debugf("Stopping container %s", safeShortID(containerID))
	if err := h.dockerClient.StopContainer(ctx, containerID, stopTimeout); err != nil {
		h.log.WithError(err).Warn("Failed to stop container gracefully, continuing with rename")
	}

	// Rename to backup name to free the original name
	h.log.Debugf("Renaming container to backup: %s", backupName)
	if err := h.dockerClient.RenameContainer(ctx, containerID, backupName); err != nil {
		return "", fmt.Errorf("failed to rename container to backup: %w", err)
	}

	h.log.Infof("Created backup: %s (original: %s)", backupName, containerName)
	return backupName, nil
}

// restoreBackup restores the backup container to its original name and starts it.
func (h *UpdateHandler) restoreBackup(ctx context.Context, backupName, originalName string) {
	h.log.Warnf("Restoring backup %s to %s", backupName, originalName)

	// Find backup container
	backupID, err := h.dockerClient.GetContainerByName(ctx, backupName)
	if err != nil || backupID == "" {
		h.log.WithError(err).Errorf("CRITICAL: Failed to find backup container %s", backupName)
		return
	}

	// Inspect backup to check its state
	backupInspect, err := h.dockerClient.InspectContainer(ctx, backupID)
	if err != nil {
		h.log.WithError(err).Errorf("Failed to inspect backup container %s", backupName)
		return
	}

	// Handle various backup states
	backupStatus := backupInspect.State.Status
	h.log.Infof("Backup container %s status: %s", backupName, backupStatus)

	switch backupStatus {
	case "running":
		h.log.Warn("Backup is running (unexpected), stopping first")
		if err := h.dockerClient.StopContainer(ctx, backupID, 10); err != nil {
			h.dockerClient.KillContainer(ctx, backupID)
		}
	case "restarting", "dead":
		h.log.Warnf("Backup in %s state, killing", backupStatus)
		h.dockerClient.KillContainer(ctx, backupID)
	}

	// Remove any container with the original name (failed new container)
	existingID, _ := h.dockerClient.GetContainerByName(ctx, originalName)
	if existingID != "" {
		h.log.Debugf("Removing failed container %s to restore backup", safeShortID(existingID))
		h.dockerClient.RemoveContainer(ctx, existingID, true)
	}

	// Rename backup to original name
	if err := h.dockerClient.RenameContainer(ctx, backupID, originalName); err != nil {
		h.log.WithError(err).Errorf("CRITICAL: Failed to rename backup to %s", originalName)
		return
	}

	// Start the restored container
	if err := h.dockerClient.StartContainer(ctx, backupID); err != nil {
		h.log.WithError(err).Errorf("CRITICAL: Failed to start restored container %s", originalName)
		return
	}

	h.log.Warnf("Successfully restored backup to %s", originalName)
}

// removeBackup removes the backup container after successful update.
func (h *UpdateHandler) removeBackup(ctx context.Context, backupName string) {
	backupID, err := h.dockerClient.GetContainerByName(ctx, backupName)
	if err != nil || backupID == "" {
		h.log.WithError(err).Warnf("Backup container %s not found for cleanup", backupName)
		return
	}

	if err := h.dockerClient.RemoveContainer(ctx, backupID, true); err != nil {
		h.log.WithError(err).Warnf("Failed to remove backup container %s", backupName)
	} else {
		h.log.Infof("Removed backup container %s", backupName)
	}
}

// waitForHealthy waits for a container to become healthy or timeout.
// This function matches the Python backend's health check logic:
// 1. If container has Docker HEALTHCHECK: Poll for "healthy" status
//    - Grace period: min(30s, 50% of timeout) treats "unhealthy" like "starting"
//    - After grace period: "unhealthy" triggers rollback
// 2. If no health check: Wait 3s for stability, verify still running
func (h *UpdateHandler) waitForHealthy(ctx context.Context, containerID string, timeout int) error {
	startTime := time.Now()
	deadline := startTime.Add(time.Duration(timeout) * time.Second)
	checkInterval := 2 * time.Second

	// Grace period for containers with health checks: allow "unhealthy" status during startup
	// Use min(30s, 50% of timeout) to handle both short and long timeouts gracefully
	// This matches Python backend behavior in utils/container_health.py
	gracePeriodSeconds := float64(timeout) * 0.5
	if gracePeriodSeconds > 30 {
		gracePeriodSeconds = 30
	}
	gracePeriod := time.Duration(gracePeriodSeconds) * time.Second

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		if time.Now().After(deadline) {
			return fmt.Errorf("health check timeout after %ds", timeout)
		}

		inspect, err := h.dockerClient.InspectContainer(ctx, containerID)
		if err != nil {
			return fmt.Errorf("failed to inspect container: %w", err)
		}

		// Check if container is still running
		if !inspect.State.Running {
			return fmt.Errorf("container stopped unexpectedly (exit code: %d)", inspect.State.ExitCode)
		}

		// If no health check defined, wait 3 seconds and assume healthy
		// (matches Python backend behavior)
		if inspect.State.Health == nil {
			h.log.Debug("No health check defined, waiting 3 seconds for stability")
			select {
			case <-time.After(3 * time.Second):
				// Verify still running after stability wait
				inspect2, err := h.dockerClient.InspectContainer(ctx, containerID)
				if err != nil {
					return fmt.Errorf("failed to inspect container after stability wait: %w", err)
				}
				if !inspect2.State.Running {
					return fmt.Errorf("container crashed within 3s of starting (exit code: %d)", inspect2.State.ExitCode)
				}
				h.log.Info("Container stable after 3s, considering healthy")
				return nil
			case <-ctx.Done():
				return ctx.Err()
			}
		}

		elapsed := time.Since(startTime)

		switch inspect.State.Health.Status {
		case "healthy":
			h.log.Info("Container is healthy")
			return nil
		case "unhealthy":
			// Grace period: During initial startup, treat "unhealthy" like "starting"
			// This prevents false negatives for slow-starting containers (e.g., Immich)
			if elapsed < gracePeriod {
				h.log.Warnf("Container is unhealthy at %.1fs, within %.0fs grace period - continuing to wait",
					elapsed.Seconds(), gracePeriod.Seconds())
			} else {
				// Grace period expired - trust the unhealthy status
				h.log.Errorf("Container is unhealthy after %.0fs grace period", gracePeriod.Seconds())
				return fmt.Errorf("container is unhealthy")
			}
		case "starting":
			h.log.Debug("Container health is starting, waiting...")
		default:
			h.log.Debugf("Unknown health status: %s, waiting...", inspect.State.Health.Status)
		}

		select {
		case <-time.After(checkInterval):
			continue
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

// sendProgress sends an update progress event to the backend.
func (h *UpdateHandler) sendProgress(containerID, stage, message string) {
	shortID := containerID
	if len(shortID) > 12 {
		shortID = shortID[:12]
	}

	progress := map[string]interface{}{
		"container_id": shortID,
		"stage":        stage,
		"message":      message,
	}

	if err := h.sendEvent("update_progress", progress); err != nil {
		h.log.WithError(err).Warn("Failed to send update progress")
	}
}

// sendLayerProgress sends layer-by-layer pull progress to the backend.
func (h *UpdateHandler) sendLayerProgress(containerID string, layers map[string]*layerProgress, overallPercent int, speedMbps float64) {
	shortID := containerID
	if len(shortID) > 12 {
		shortID = shortID[:12]
	}

	// Build layer list for frontend (match Python format)
	layerList := make([]map[string]interface{}, 0, len(layers))
	var downloading, extracting, complete, cached int

	for _, layer := range layers {
		percent := 0
		if layer.Total > 0 {
			percent = int((layer.Current * 100) / layer.Total)
		}

		layerList = append(layerList, map[string]interface{}{
			"id":      layer.ID,
			"status":  layer.Status,
			"current": layer.Current,
			"total":   layer.Total,
			"percent": percent,
		})

		// Count layer states for summary
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

	// Build summary message
	totalLayers := len(layers)
	var summary string
	if downloading > 0 {
		summary = fmt.Sprintf("Downloading %d of %d layers (%d%%)", downloading, totalLayers, overallPercent)
	} else if extracting > 0 {
		summary = fmt.Sprintf("Extracting %d of %d layers (%d%%)", extracting, totalLayers, overallPercent)
	} else if complete+cached == totalLayers && totalLayers > 0 {
		// All layers are either complete or cached (Already exists)
		if cached > 0 {
			summary = fmt.Sprintf("Pull complete (%d layers, %d cached)", totalLayers, cached)
		} else {
			summary = fmt.Sprintf("Pull complete (%d layers)", totalLayers)
		}
	} else {
		summary = fmt.Sprintf("Pulling image (%d%%)", overallPercent)
	}

	progress := map[string]interface{}{
		"container_id":     shortID,
		"overall_progress": overallPercent,
		"layers":           layerList,
		"total_layers":     totalLayers,
		"remaining_layers": 0,
		"summary":          summary,
		"speed_mbps":       speedMbps,
	}

	if err := h.sendEvent("update_layer_progress", progress); err != nil {
		h.log.WithError(err).Debug("Failed to send layer progress")
	}
}

// fail sends an error progress event and returns the error.
func (h *UpdateHandler) fail(containerID, stage string, err error) error {
	shortID := containerID
	if len(shortID) > 12 {
		shortID = shortID[:12]
	}

	progress := map[string]interface{}{
		"container_id": shortID,
		"stage":        stage,
		"message":      "Error occurred",
		"error":        err.Error(),
	}

	if sendErr := h.sendEvent("update_progress", progress); sendErr != nil {
		h.log.WithError(sendErr).Warn("Failed to send error progress")
	}

	return err
}
