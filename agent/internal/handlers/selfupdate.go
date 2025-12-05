package handlers

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/docker"
	dockerTypes "github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/sirupsen/logrus"
)

// SelfUpdateHandler manages agent self-updates
// Supports two modes:
// - Container mode: Updates own container (when running in Docker)
// - Native mode: Binary swap (when running as system service)
type SelfUpdateHandler struct {
	myContainerID string
	dataDir       string
	log           *logrus.Logger
	sendEvent     func(msgType string, payload interface{}) error
	dockerClient  *docker.Client
	stopSignal    func() // Signal to stop the agent gracefully
}

// NewSelfUpdateHandler creates a new self-update handler
func NewSelfUpdateHandler(
	myContainerID, dataDir string,
	log *logrus.Logger,
	sendEvent func(string, interface{}) error,
	dockerClient *docker.Client,
	stopSignal func(),
) *SelfUpdateHandler {
	return &SelfUpdateHandler{
		myContainerID: myContainerID,
		dataDir:       dataDir,
		log:           log,
		sendEvent:     sendEvent,
		dockerClient:  dockerClient,
		stopSignal:    stopSignal,
	}
}

// SelfUpdateRequest contains parameters for self-update
// Backend sends both image and binary_url, agent picks based on deployment mode
type SelfUpdateRequest struct {
	Version   string `json:"version"`
	Image     string `json:"image"`                // For container mode
	BinaryURL string `json:"binary_url,omitempty"` // For native mode
	Checksum  string `json:"checksum,omitempty"`
}

// SelfUpdateProgress represents self-update progress events
type SelfUpdateProgress struct {
	Stage   string `json:"stage"`
	Message string `json:"message"`
	Error   string `json:"error,omitempty"`
}

// UpdateLockFile represents the coordination file for native mode updates
type UpdateLockFile struct {
	Version       string    `json:"version"`
	NewBinaryPath string    `json:"new_binary_path"`
	OldBinaryPath string    `json:"old_binary_path"`
	Timestamp     time.Time `json:"timestamp"`
}

// PerformSelfUpdate performs self-update based on deployment mode
func (h *SelfUpdateHandler) PerformSelfUpdate(ctx context.Context, req SelfUpdateRequest) error {
	h.log.WithFields(logrus.Fields{
		"version":       req.Version,
		"image":         req.Image,
		"binary_url":    req.BinaryURL,
		"container_id":  h.myContainerID,
		"container_mode": h.myContainerID != "",
	}).Info("Starting self-update")

	// Branch based on deployment mode
	if h.myContainerID != "" {
		// Container mode: Update own container
		return h.performContainerSelfUpdate(ctx, req)
	}

	// Native mode: Binary swap
	return h.performNativeSelfUpdate(ctx, req)
}

// performContainerSelfUpdate updates the agent's own container
// Flow:
// 1. Pull new image
// 2. Inspect own container to get config
// 3. Create new container with same config but new image
// 4. Start new container
// 5. Wait for it to be healthy
// 6. Stop ourselves (old container)
func (h *SelfUpdateHandler) performContainerSelfUpdate(ctx context.Context, req SelfUpdateRequest) error {
	if req.Image == "" {
		return fmt.Errorf("image is required for container self-update")
	}

	if h.dockerClient == nil {
		return fmt.Errorf("docker client not available for container self-update")
	}

	h.log.WithFields(logrus.Fields{
		"container_id": h.myContainerID,
		"new_image":    req.Image,
	}).Info("Performing container-based self-update")

	// Step 1: Pull new image
	h.sendProgress("pull", fmt.Sprintf("Pulling image %s", req.Image))
	if err := h.dockerClient.PullImage(ctx, req.Image); err != nil {
		h.sendProgressError("pull", err)
		return fmt.Errorf("failed to pull image: %w", err)
	}

	// Step 2: Inspect own container to get configuration
	h.sendProgress("inspect", "Inspecting current container")
	oldContainer, err := h.dockerClient.InspectContainer(ctx, h.myContainerID)
	if err != nil {
		h.sendProgressError("inspect", err)
		return fmt.Errorf("failed to inspect own container: %w", err)
	}

	originalName := oldContainer.Name
	// Docker returns name with leading slash, remove it
	if len(originalName) > 0 && originalName[0] == '/' {
		originalName = originalName[1:]
	}

	h.log.WithField("original_name", originalName).Debug("Got container configuration")

	// Step 3: Create new container with same config but new image
	h.sendProgress("create", "Creating new container")
	newConfig := h.cloneContainerConfig(&oldContainer, req.Image)
	newHostConfig := h.cloneHostConfig(oldContainer.HostConfig)

	// Use temporary name - will be renamed after old container is removed
	tempName := originalName + "-update"

	newContainerID, err := h.dockerClient.CreateContainer(ctx, newConfig, newHostConfig, tempName)
	if err != nil {
		h.sendProgressError("create", err)
		return fmt.Errorf("failed to create new container: %w", err)
	}

	h.log.WithField("new_container_id", safeShortID(newContainerID)).Info("Created new container")

	// Step 4: Write cleanup file BEFORE starting new container
	// This ensures the new agent finds it on startup (race condition fix)
	cleanupFile := filepath.Join(h.dataDir, "cleanup.json")
	cleanupData := map[string]string{
		"old_container_id":   h.myContainerID,
		"old_container_name": originalName,
		"new_container_id":   newContainerID,
		"temp_name":          tempName,
		"original_name":      originalName,
	}
	if data, err := json.MarshalIndent(cleanupData, "", "  "); err == nil {
		if err := os.WriteFile(cleanupFile, data, 0644); err != nil {
			h.log.WithError(err).Error("Failed to write cleanup file")
			// Continue anyway - cleanup can be done manually
		}
	}

	// Step 5: Start new container
	h.sendProgress("start", "Starting new container")
	if err := h.dockerClient.StartContainer(ctx, newContainerID); err != nil {
		// Cleanup: remove the failed container and cleanup file
		h.dockerClient.RemoveContainer(ctx, newContainerID, true)
		os.Remove(cleanupFile)
		h.sendProgressError("start", err)
		return fmt.Errorf("failed to start new container: %w", err)
	}

	// Step 6: Wait for new container to be healthy
	h.sendProgress("health", "Waiting for new container to be healthy")
	if err := h.waitForHealthy(ctx, newContainerID, 60); err != nil {
		h.log.WithError(err).Warn("New container failed health check, rolling back")
		// Rollback: stop and remove new container, remove cleanup file
		h.dockerClient.StopContainer(ctx, newContainerID, 10)
		h.dockerClient.RemoveContainer(ctx, newContainerID, true)
		os.Remove(cleanupFile)
		h.sendProgressError("health", err)
		return fmt.Errorf("new container health check failed: %w", err)
	}

	h.log.Info("New container is healthy")

	// Step 7: Signal completion and stop ourselves
	h.sendProgress("complete", "Self-update complete, stopping old container")

	h.log.Info("Self-update successful, stopping old container")

	// Give a moment for the progress event to be sent
	time.Sleep(500 * time.Millisecond)

	// Signal graceful shutdown - this will cause the agent to exit cleanly
	// Docker will NOT restart us because we're stopping gracefully
	if h.stopSignal != nil {
		h.stopSignal()
	}

	return nil
}

// performNativeSelfUpdate performs binary swap for native/systemd deployments
func (h *SelfUpdateHandler) performNativeSelfUpdate(ctx context.Context, req SelfUpdateRequest) error {
	if req.BinaryURL == "" {
		return fmt.Errorf("binary_url is required for native self-update")
	}

	h.log.WithFields(logrus.Fields{
		"version":    req.Version,
		"binary_url": req.BinaryURL,
	}).Info("Performing native binary self-update")

	// Step 1: Download new binary
	h.sendProgress("download", fmt.Sprintf("Downloading version %s", req.Version))

	newBinaryPath := filepath.Join(h.dataDir, "agent-new")
	if err := h.downloadBinary(ctx, req.BinaryURL, newBinaryPath); err != nil {
		h.sendProgressError("download", err)
		return fmt.Errorf("failed to download binary: %w", err)
	}

	// Step 2: Verify checksum if provided
	if req.Checksum != "" {
		h.sendProgress("verify", "Verifying checksum")

		actualChecksum, err := h.computeFileChecksum(newBinaryPath)
		if err != nil {
			h.sendProgressError("verify", err)
			os.Remove(newBinaryPath)
			return fmt.Errorf("failed to compute checksum: %w", err)
		}

		if actualChecksum != req.Checksum {
			err := fmt.Errorf("checksum mismatch: expected %s, got %s", req.Checksum, actualChecksum)
			h.sendProgressError("verify", err)
			os.Remove(newBinaryPath)
			return err
		}

		h.log.Info("Checksum verified successfully")
	}

	// Step 3: Make binary executable
	if err := os.Chmod(newBinaryPath, 0755); err != nil {
		h.sendProgressError("chmod", err)
		return fmt.Errorf("failed to make binary executable: %w", err)
	}

	// Step 4: Write update lock file
	h.sendProgress("prepare", "Preparing update coordination")
	lockFile := UpdateLockFile{
		Version:       req.Version,
		NewBinaryPath: newBinaryPath,
		OldBinaryPath: "/app/agent", // Current binary path
		Timestamp:     time.Now(),
	}

	lockFilePath := filepath.Join(h.dataDir, "update.lock")
	if err := h.writeLockFile(lockFilePath, &lockFile); err != nil {
		h.sendProgressError("prepare", err)
		return fmt.Errorf("failed to write lock file: %w", err)
	}

	h.sendProgress("complete", "Update prepared, agent will restart")

	h.log.Info("Native self-update prepared, signaling shutdown")

	// Signal shutdown so systemd can restart us
	if h.stopSignal != nil {
		h.stopSignal()
	}

	return nil
}

// CheckAndApplyUpdate checks for pending updates on startup
// For native mode: applies binary swap from lock file
// For container mode: cleans up old container from cleanup file
func (h *SelfUpdateHandler) CheckAndApplyUpdate() error {
	// Check for native mode update lock
	lockFilePath := filepath.Join(h.dataDir, "update.lock")
	if _, err := os.Stat(lockFilePath); err == nil {
		return h.applyNativeUpdate(lockFilePath)
	}

	// Check for container mode cleanup
	cleanupFilePath := filepath.Join(h.dataDir, "cleanup.json")
	if _, err := os.Stat(cleanupFilePath); err == nil {
		return h.performContainerCleanup(cleanupFilePath)
	}

	return nil
}

// applyNativeUpdate applies a pending native binary update
func (h *SelfUpdateHandler) applyNativeUpdate(lockFilePath string) error {
	h.log.Info("Found pending native update, applying...")

	// Read lock file
	lockFile, err := h.readLockFile(lockFilePath)
	if err != nil {
		h.log.WithError(err).Error("Failed to read lock file")
		os.Remove(lockFilePath)
		return fmt.Errorf("failed to read lock file: %w", err)
	}

	// Check if new binary exists
	if _, err := os.Stat(lockFile.NewBinaryPath); os.IsNotExist(err) {
		h.log.Error("New binary not found, aborting update")
		os.Remove(lockFilePath)
		return fmt.Errorf("new binary not found: %s", lockFile.NewBinaryPath)
	}

	// Backup old binary
	backupPath := lockFile.OldBinaryPath + ".backup"
	if err := h.copyFile(lockFile.OldBinaryPath, backupPath); err != nil {
		h.log.WithError(err).Warn("Failed to backup old binary")
		// Continue anyway
	}

	// Replace old binary with new binary
	if err := os.Rename(lockFile.NewBinaryPath, lockFile.OldBinaryPath); err != nil {
		h.log.WithError(err).Error("Failed to replace binary")
		// Try to restore backup
		if backupErr := os.Rename(backupPath, lockFile.OldBinaryPath); backupErr != nil {
			h.log.WithError(backupErr).Fatal("Failed to restore backup, agent may be broken!")
		}
		os.Remove(lockFilePath)
		return fmt.Errorf("failed to replace binary: %w", err)
	}

	// Make new binary executable
	if err := os.Chmod(lockFile.OldBinaryPath, 0755); err != nil {
		h.log.WithError(err).Error("Failed to make new binary executable")
	}

	// Clean up
	os.Remove(backupPath)
	os.Remove(lockFilePath)

	h.log.WithField("version", lockFile.Version).Info("Native self-update applied successfully")

	return nil
}

// performContainerCleanup cleans up after container self-update
func (h *SelfUpdateHandler) performContainerCleanup(cleanupFilePath string) error {
	h.log.Info("Found container cleanup file, performing cleanup...")

	// Read cleanup file
	data, err := os.ReadFile(cleanupFilePath)
	if err != nil {
		h.log.WithError(err).Error("Failed to read cleanup file")
		os.Remove(cleanupFilePath)
		return err
	}

	var cleanup map[string]string
	if err := json.Unmarshal(data, &cleanup); err != nil {
		h.log.WithError(err).Error("Failed to parse cleanup file")
		os.Remove(cleanupFilePath)
		return err
	}

	oldContainerID := cleanup["old_container_id"]
	originalName := cleanup["original_name"]

	if h.dockerClient == nil {
		h.log.Warn("Docker client not available for cleanup")
		os.Remove(cleanupFilePath)
		return nil
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	// Stop and remove old container
	if oldContainerID != "" {
		h.log.WithField("container_id", safeShortID(oldContainerID)).Info("Removing old container")
		h.dockerClient.StopContainer(ctx, oldContainerID, 10)
		if err := h.dockerClient.RemoveContainer(ctx, oldContainerID, true); err != nil {
			h.log.WithError(err).Warn("Failed to remove old container")
		}
	}

	// Rename ourselves to original name
	if originalName != "" && h.myContainerID != "" {
		h.log.WithField("name", originalName).Info("Renaming to original name")
		if err := h.dockerClient.RenameContainer(ctx, h.myContainerID, originalName); err != nil {
			h.log.WithError(err).Warn("Failed to rename container")
		}
	}

	// Clean up the cleanup file
	os.Remove(cleanupFilePath)

	h.log.Info("Container cleanup completed")

	return nil
}

// cloneContainerConfig creates a new container config based on existing container
func (h *SelfUpdateHandler) cloneContainerConfig(inspect *dockerTypes.ContainerJSON, newImage string) *container.Config {
	config := inspect.Config

	return &container.Config{
		// Don't clone Hostname - let Docker assign a new one so the new container
		// gets its own identity (container ID detection uses HOSTNAME)
		Hostname:     "",
		Domainname:   config.Domainname,
		User:         config.User,
		AttachStdin:  config.AttachStdin,
		AttachStdout: config.AttachStdout,
		AttachStderr: config.AttachStderr,
		Tty:          config.Tty,
		OpenStdin:    config.OpenStdin,
		StdinOnce:    config.StdinOnce,
		Env:          config.Env,
		Cmd:          config.Cmd,
		Image:        newImage, // Use new image
		WorkingDir:   config.WorkingDir,
		Entrypoint:   config.Entrypoint,
		Labels:       config.Labels,
		StopSignal:   config.StopSignal,
		StopTimeout:  config.StopTimeout,
	}
}

// cloneHostConfig creates a new host config based on existing container
func (h *SelfUpdateHandler) cloneHostConfig(hostConfig *container.HostConfig) *container.HostConfig {
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
func (h *SelfUpdateHandler) waitForHealthy(ctx context.Context, containerID string, timeout int) error {
	deadline := time.Now().Add(time.Duration(timeout) * time.Second)

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

		if !inspect.State.Running {
			return fmt.Errorf("container stopped unexpectedly")
		}

		// If no health check defined, wait a few seconds and assume healthy
		if inspect.State.Health == nil {
			h.log.Debug("No health check defined, waiting 5 seconds")
			select {
			case <-time.After(5 * time.Second):
				return nil
			case <-ctx.Done():
				return ctx.Err()
			}
		}

		switch inspect.State.Health.Status {
		case "healthy":
			h.log.Info("Container is healthy")
			return nil
		case "unhealthy":
			return fmt.Errorf("container is unhealthy")
		case "starting":
			h.log.Debug("Container health is starting, waiting...")
			select {
			case <-time.After(2 * time.Second):
				continue
			case <-ctx.Done():
				return ctx.Err()
			}
		default:
			h.log.Debugf("Unknown health status: %s", inspect.State.Health.Status)
			select {
			case <-time.After(2 * time.Second):
				continue
			case <-ctx.Done():
				return ctx.Err()
			}
		}
	}
}

// downloadBinary downloads a binary from URL to destination
func (h *SelfUpdateHandler) downloadBinary(ctx context.Context, url, dest string) error {
	client := &http.Client{
		Timeout: 5 * time.Minute,
	}

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("failed to download: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download failed with status: %d", resp.StatusCode)
	}

	out, err := os.Create(dest)
	if err != nil {
		return fmt.Errorf("failed to create file: %w", err)
	}
	defer out.Close()

	_, err = io.Copy(out, resp.Body)
	if err != nil {
		return fmt.Errorf("failed to write file: %w", err)
	}

	return nil
}

// copyFile copies a file from src to dst
func (h *SelfUpdateHandler) copyFile(src, dst string) error {
	sourceFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer sourceFile.Close()

	destFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer destFile.Close()

	_, err = io.Copy(destFile, sourceFile)
	return err
}

// writeLockFile writes the update lock file
func (h *SelfUpdateHandler) writeLockFile(path string, lockFile *UpdateLockFile) error {
	data, err := json.MarshalIndent(lockFile, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal lock file: %w", err)
	}

	if err := os.WriteFile(path, data, 0644); err != nil {
		return fmt.Errorf("failed to write lock file: %w", err)
	}

	return nil
}

// readLockFile reads the update lock file
func (h *SelfUpdateHandler) readLockFile(path string) (*UpdateLockFile, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read lock file: %w", err)
	}

	var lockFile UpdateLockFile
	if err := json.Unmarshal(data, &lockFile); err != nil {
		return nil, fmt.Errorf("failed to unmarshal lock file: %w", err)
	}

	return &lockFile, nil
}

// sendProgress sends a self-update progress event
func (h *SelfUpdateHandler) sendProgress(stage, message string) {
	progress := SelfUpdateProgress{
		Stage:   stage,
		Message: message,
	}

	if err := h.sendEvent("selfupdate_progress", progress); err != nil {
		h.log.WithError(err).Warn("Failed to send self-update progress")
	}
}

// sendProgressError sends a self-update progress error event
func (h *SelfUpdateHandler) sendProgressError(stage string, err error) {
	progress := SelfUpdateProgress{
		Stage:   stage,
		Message: "Error occurred",
		Error:   err.Error(),
	}

	if sendErr := h.sendEvent("selfupdate_progress", progress); sendErr != nil {
		h.log.WithError(sendErr).Warn("Failed to send self-update progress error")
	}
}

// computeFileChecksum computes SHA256 checksum of a file
func (h *SelfUpdateHandler) computeFileChecksum(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", fmt.Errorf("failed to open file: %w", err)
	}
	defer f.Close()

	hash := sha256.New()
	if _, err := io.Copy(hash, f); err != nil {
		return "", fmt.Errorf("failed to compute hash: %w", err)
	}

	return hex.EncodeToString(hash.Sum(nil)), nil
}
