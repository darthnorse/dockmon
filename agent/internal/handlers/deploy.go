package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/sirupsen/logrus"
)

// DeployHandler manages compose deployments using native Docker Compose
type DeployHandler struct {
	dockerClient *docker.Client
	log          *logrus.Logger
	sendEvent    func(msgType string, payload interface{}) error
	composeCmd   []string // e.g., ["docker", "compose"] or ["docker-compose"]
}

// DeployComposeRequest is sent from backend to agent
type DeployComposeRequest struct {
	DeploymentID   string            `json:"deployment_id"`
	ProjectName    string            `json:"project_name"`
	ComposeContent string            `json:"compose_content"`
	Environment    map[string]string `json:"environment,omitempty"`
	Action         string            `json:"action"`         // "up", "down", "restart"
	RemoveVolumes  bool              `json:"remove_volumes"` // Only for "down" action, default false
}

// DeployComposeResult is sent from agent to backend on completion
type DeployComposeResult struct {
	DeploymentID string                   `json:"deployment_id"`
	Success      bool                     `json:"success"`
	Services     map[string]ServiceResult `json:"services,omitempty"`
	Error        string                   `json:"error,omitempty"`
}

// ServiceResult contains info about a deployed service
type ServiceResult struct {
	ContainerID   string `json:"container_id"`   // 12-char short ID
	ContainerName string `json:"container_name"`
	Image         string `json:"image"`
	Status        string `json:"status"` // "running", "created", "exited", etc.
	Error         string `json:"error,omitempty"`
}

// Deploy progress stages (coarse, no output parsing)
const (
	DeployStageStarting  = "starting"  // Deployment initiated
	DeployStageExecuting = "executing" // Compose command running
	DeployStageCompleted = "completed" // Success - querying containers
	DeployStageFailed    = "failed"    // Compose returned error
)

// NewDeployHandler creates a new deploy handler and detects compose command
func NewDeployHandler(
	ctx context.Context,
	dockerClient *docker.Client,
	log *logrus.Logger,
	sendEvent func(string, interface{}) error,
) (*DeployHandler, error) {
	// Detect available compose command
	composeCmd := detectComposeCommand(ctx)
	if composeCmd == nil {
		return nil, fmt.Errorf("Docker Compose is not available on this host. Install docker-compose-plugin or standalone docker-compose")
	}

	log.WithField("compose_cmd", strings.Join(composeCmd, " ")).Info("Detected compose command")

	return &DeployHandler{
		dockerClient: dockerClient,
		log:          log,
		sendEvent:    sendEvent,
		composeCmd:   composeCmd,
	}, nil
}

// detectComposeCommand finds available compose command
// Returns nil if no compose command is available
func detectComposeCommand(ctx context.Context) []string {
	// Try in order of preference:
	// 1. "docker compose" (v2 plugin - recommended)
	// 2. "docker-compose" (standalone v1/v2)
	// 3. "podman-compose" (Podman)

	candidates := [][]string{
		{"docker", "compose"},
		{"docker-compose"},
		{"podman-compose"},
	}

	for _, cmd := range candidates {
		// Build version check command
		args := append(cmd, "version")

		// Run with timeout
		timeoutCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		checkCmd := exec.CommandContext(timeoutCtx, args[0], args[1:]...)
		err := checkCmd.Run()
		cancel()

		if err == nil {
			return cmd
		}
	}

	return nil
}

// DeployCompose handles the deploy_compose command
func (h *DeployHandler) DeployCompose(ctx context.Context, req DeployComposeRequest) *DeployComposeResult {
	h.log.WithFields(logrus.Fields{
		"deployment_id": req.DeploymentID,
		"project_name":  req.ProjectName,
		"action":        req.Action,
	}).Info("Starting compose deployment")

	// Send starting progress
	h.sendProgress(req.DeploymentID, DeployStageStarting, "Starting deployment...")

	// Write compose content to temp file
	composeFile, err := h.writeComposeFile(req.ComposeContent)
	if err != nil {
		return h.failResult(req.DeploymentID, fmt.Sprintf("Failed to write compose file: %v", err))
	}
	defer os.Remove(composeFile) // Cleanup temp file

	// Execute based on action
	var result *DeployComposeResult

	switch req.Action {
	case "up":
		result = h.runComposeUp(ctx, req, composeFile)
	case "down":
		result = h.runComposeDown(ctx, req, composeFile)
	case "restart":
		// Restart = down + up
		h.sendProgress(req.DeploymentID, DeployStageExecuting, "Stopping services...")
		downReq := req
		downReq.RemoveVolumes = false // Don't remove volumes on restart
		downResult := h.runComposeDown(ctx, downReq, composeFile)
		if !downResult.Success {
			return downResult
		}

		h.sendProgress(req.DeploymentID, DeployStageExecuting, "Starting services...")
		result = h.runComposeUp(ctx, req, composeFile)
	default:
		result = h.failResult(req.DeploymentID, fmt.Sprintf("Unknown action: %s", req.Action))
	}

	return result
}

// writeComposeFile writes compose content to a temp file with restrictive permissions
func (h *DeployHandler) writeComposeFile(content string) (string, error) {
	f, err := os.CreateTemp("", "dockmon-compose-*.yml")
	if err != nil {
		return "", fmt.Errorf("failed to create temp file: %w", err)
	}

	// Restrictive permissions (owner read/write only)
	if err := f.Chmod(0600); err != nil {
		os.Remove(f.Name())
		return "", fmt.Errorf("failed to set file permissions: %w", err)
	}

	if _, err := f.WriteString(content); err != nil {
		os.Remove(f.Name())
		return "", fmt.Errorf("failed to write content: %w", err)
	}

	if err := f.Close(); err != nil {
		os.Remove(f.Name())
		return "", fmt.Errorf("failed to close file: %w", err)
	}

	return f.Name(), nil
}

// runComposeUp executes docker compose up
func (h *DeployHandler) runComposeUp(ctx context.Context, req DeployComposeRequest, composeFile string) *DeployComposeResult {
	h.sendProgress(req.DeploymentID, DeployStageExecuting, "Running compose up...")

	// Build command: docker compose -f <file> -p <project> up -d --remove-orphans
	args := append([]string{}, h.composeCmd[1:]...)
	args = append(args, "-f", composeFile, "-p", req.ProjectName, "up", "-d", "--remove-orphans")

	stdout, stderr, err := h.runCompose(ctx, req.Environment, args...)
	if err != nil {
		errMsg := parseComposeError(stderr)
		if errMsg == "" {
			errMsg = err.Error()
		}
		h.log.WithFields(logrus.Fields{
			"error":  errMsg,
			"stdout": stdout,
			"stderr": stderr,
		}).Error("Compose up failed")

		// Attempt cleanup on failure
		h.log.Warn("Deployment failed, attempting cleanup...")
		cleanupArgs := append([]string{}, h.composeCmd[1:]...)
		cleanupArgs = append(cleanupArgs, "-f", composeFile, "-p", req.ProjectName, "down", "--remove-orphans")
		h.runCompose(ctx, nil, cleanupArgs...)

		return h.failResult(req.DeploymentID, errMsg)
	}

	// Discover containers after successful deployment
	h.sendProgress(req.DeploymentID, DeployStageCompleted, "Discovering containers...")
	services, discoverErr := h.discoverContainers(ctx, req.ProjectName)
	if discoverErr != nil {
		h.log.WithError(discoverErr).Warn("Failed to discover containers after deployment")
		// Deployment succeeded but discovery failed - report partial success
		return &DeployComposeResult{
			DeploymentID: req.DeploymentID,
			Success:      true,
			Services:     make(map[string]ServiceResult),
			Error:        fmt.Sprintf("Deployment succeeded but container discovery failed: %v", discoverErr),
		}
	}

	h.log.WithFields(logrus.Fields{
		"deployment_id":  req.DeploymentID,
		"services_count": len(services),
	}).Info("Compose deployment completed successfully")

	return &DeployComposeResult{
		DeploymentID: req.DeploymentID,
		Success:      true,
		Services:     services,
	}
}

// runComposeDown executes docker compose down
func (h *DeployHandler) runComposeDown(ctx context.Context, req DeployComposeRequest, composeFile string) *DeployComposeResult {
	h.sendProgress(req.DeploymentID, DeployStageExecuting, "Running compose down...")

	// Build command: docker compose -f <file> -p <project> down --remove-orphans [--volumes]
	args := append([]string{}, h.composeCmd[1:]...)
	args = append(args, "-f", composeFile, "-p", req.ProjectName, "down", "--remove-orphans")
	if req.RemoveVolumes {
		args = append(args, "--volumes")
		h.log.Warn("Removing volumes as requested (destructive operation)")
	}

	_, stderr, err := h.runCompose(ctx, nil, args...)
	if err != nil {
		errMsg := parseComposeError(stderr)
		if errMsg == "" {
			errMsg = err.Error()
		}
		h.log.WithError(err).Error("Compose down failed")
		return h.failResult(req.DeploymentID, errMsg)
	}

	h.log.WithField("deployment_id", req.DeploymentID).Info("Compose down completed successfully")

	return &DeployComposeResult{
		DeploymentID: req.DeploymentID,
		Success:      true,
		Services:     make(map[string]ServiceResult),
	}
}

// runCompose executes compose command with environment
func (h *DeployHandler) runCompose(ctx context.Context, env map[string]string, args ...string) (string, string, error) {
	cmd := exec.CommandContext(ctx, h.composeCmd[0], args...)

	// Scope environment to this command only
	// Using os.Setenv would be process-wide and not thread-safe
	cmd.Env = h.buildEnv(env)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	return stdout.String(), stderr.String(), err
}

// buildEnv builds environment for compose command
func (h *DeployHandler) buildEnv(env map[string]string) []string {
	// Start with current environment
	result := os.Environ()

	// Add deployment-specific variables
	for key, value := range env {
		result = append(result, fmt.Sprintf("%s=%s", key, value))
	}

	return result
}

// discoverContainers finds containers created by compose using Docker labels
func (h *DeployHandler) discoverContainers(ctx context.Context, projectName string) (map[string]ServiceResult, error) {
	// Compose adds labels: com.docker.compose.project=<name>
	containers, err := h.dockerClient.ListAllContainers(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to list containers: %w", err)
	}

	services := make(map[string]ServiceResult)

	for _, c := range containers {
		// Check if container belongs to this compose project
		if c.Labels["com.docker.compose.project"] != projectName {
			continue
		}

		serviceName := c.Labels["com.docker.compose.service"]
		if serviceName == "" {
			serviceName = "unknown"
		}

		// Get container name (remove leading /)
		containerName := ""
		if len(c.Names) > 0 {
			containerName = strings.TrimPrefix(c.Names[0], "/")
		}

		// Get image name
		imageName := c.Image

		// Get status
		status := c.State
		if status == "" {
			status = c.Status
		}

		// Use short ID (12 chars)
		shortID := c.ID
		if len(shortID) > 12 {
			shortID = shortID[:12]
		}

		services[serviceName] = ServiceResult{
			ContainerID:   shortID,
			ContainerName: containerName,
			Image:         imageName,
			Status:        status,
		}

		h.log.WithFields(logrus.Fields{
			"service":      serviceName,
			"container_id": shortID,
			"name":         containerName,
			"status":       status,
		}).Debug("Discovered compose service")
	}

	return services, nil
}

// sendProgress sends a deploy progress event to the backend
func (h *DeployHandler) sendProgress(deploymentID, stage, message string) {
	progress := map[string]interface{}{
		"deployment_id": deploymentID,
		"stage":         stage,
		"message":       message,
	}

	if err := h.sendEvent("deploy_progress", progress); err != nil {
		h.log.WithError(err).Warn("Failed to send deploy progress")
	}
}

// failResult creates a failure result and sends failed progress event
func (h *DeployHandler) failResult(deploymentID, errorMsg string) *DeployComposeResult {
	h.sendProgress(deploymentID, DeployStageFailed, errorMsg)

	return &DeployComposeResult{
		DeploymentID: deploymentID,
		Success:      false,
		Error:        errorMsg,
	}
}

// parseComposeError extracts meaningful error from compose stderr
func parseComposeError(stderr string) string {
	stderr = strings.TrimSpace(stderr)
	if stderr == "" {
		return ""
	}

	// If stderr is very long, truncate to last meaningful portion
	// Compose often outputs progress lines before the error
	lines := strings.Split(stderr, "\n")
	if len(lines) > 10 {
		// Return last 10 lines - usually contains the actual error
		return strings.Join(lines[len(lines)-10:], "\n")
	}

	return stderr
}

// HasComposeSupport returns true if compose is available
func (h *DeployHandler) HasComposeSupport() bool {
	return h.composeCmd != nil
}

// GetComposeCommand returns the detected compose command
func (h *DeployHandler) GetComposeCommand() string {
	if h.composeCmd == nil {
		return ""
	}
	return strings.Join(h.composeCmd, " ")
}

// ComposePs executes docker compose ps --format json to get container info
func (h *DeployHandler) ComposePs(ctx context.Context, projectName string, composeFile string) ([]ComposeContainer, error) {
	args := append([]string{}, h.composeCmd[1:]...)
	args = append(args, "-f", composeFile, "-p", projectName, "ps", "--format", "json")

	stdout, _, err := h.runCompose(ctx, nil, args...)
	if err != nil {
		return nil, fmt.Errorf("compose ps failed: %w", err)
	}

	// Parse JSON output (each line is a JSON object for compose v2)
	var containers []ComposeContainer
	lines := strings.Split(strings.TrimSpace(stdout), "\n")
	for _, line := range lines {
		if line == "" {
			continue
		}

		var c ComposeContainer
		if err := json.Unmarshal([]byte(line), &c); err != nil {
			h.log.WithError(err).Warn("Failed to parse compose ps output line")
			continue
		}
		containers = append(containers, c)
	}

	return containers, nil
}

// ComposeContainer represents output from docker compose ps --format json
type ComposeContainer struct {
	ID      string `json:"ID"`
	Name    string `json:"Name"`
	Service string `json:"Service"`
	State   string `json:"State"`
	Status  string `json:"Status"`
	Image   string `json:"Image"`
}
