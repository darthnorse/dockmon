package handlers

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/compose-spec/compose-go/v2/cli"
	"github.com/compose-spec/compose-go/v2/types"
	"github.com/darthnorse/dockmon-agent/internal/docker"
	dockercli "github.com/docker/cli/cli/command"
	"github.com/docker/cli/cli/flags"
	"github.com/docker/compose/v2/pkg/api"
	"github.com/docker/compose/v2/pkg/compose"
	"github.com/sirupsen/logrus"
)

// DeployHandler manages compose deployments using Docker Compose Go library
type DeployHandler struct {
	dockerClient *docker.Client
	log          *logrus.Logger
	sendEvent    func(msgType string, payload interface{}) error
	mu           sync.Mutex
}

// DeployComposeRequest is sent from backend to agent
type DeployComposeRequest struct {
	DeploymentID   string            `json:"deployment_id"`
	ProjectName    string            `json:"project_name"`
	ComposeContent string            `json:"compose_content"`
	Environment    map[string]string `json:"environment,omitempty"`
	Action         string            `json:"action"`         // "up", "down", "restart"
	RemoveVolumes  bool              `json:"remove_volumes"` // Only for "down" action, default false
	Profiles       []string          `json:"profiles,omitempty"`
	WaitForHealthy bool              `json:"wait_for_healthy,omitempty"`
	HealthTimeout  int               `json:"health_timeout,omitempty"`
}

// DeployComposeResult is sent from agent to backend on completion
type DeployComposeResult struct {
	DeploymentID   string                   `json:"deployment_id"`
	Success        bool                     `json:"success"`
	PartialSuccess bool                     `json:"partial_success,omitempty"`
	Services       map[string]ServiceResult `json:"services,omitempty"`
	FailedServices []string                 `json:"failed_services,omitempty"`
	Error          string                   `json:"error,omitempty"`
}

// ServiceResult contains info about a deployed service
type ServiceResult struct {
	ContainerID   string `json:"container_id"`
	ContainerName string `json:"container_name"`
	Image         string `json:"image"`
	Status        string `json:"status"`
	Error         string `json:"error,omitempty"`
}

// Deploy progress stages
const (
	DeployStageStarting      = "starting"
	DeployStageExecuting     = "executing"
	DeployStageWaitingHealth = "waiting_for_health"
	DeployStageCompleted     = "completed"
	DeployStageFailed        = "failed"
)

// ServiceStatus represents the status of a single service during deployment
type ServiceStatus struct {
	Name    string `json:"name"`
	Status  string `json:"status"`
	Image   string `json:"image,omitempty"`
	Message string `json:"message,omitempty"`
}

// NewDeployHandler creates a new deploy handler using the Docker Compose Go library
func NewDeployHandler(
	ctx context.Context,
	dockerClient *docker.Client,
	log *logrus.Logger,
	sendEvent func(string, interface{}) error,
) (*DeployHandler, error) {
	// Test that we can create a compose service (validates library availability)
	if err := testComposeLibrary(); err != nil {
		return nil, fmt.Errorf("Docker Compose library not available: %w", err)
	}

	log.Info("Deploy handler initialized using Docker Compose Go library")

	return &DeployHandler{
		dockerClient: dockerClient,
		log:          log,
		sendEvent:    sendEvent,
	}, nil
}

// testComposeLibrary validates that the compose library is functional
func testComposeLibrary() error {
	// Create a minimal DockerCli to verify library works
	cli, err := dockercli.NewDockerCli()
	if err != nil {
		return fmt.Errorf("failed to create Docker CLI: %w", err)
	}

	opts := flags.NewClientOptions()
	if err := cli.Initialize(opts); err != nil {
		return fmt.Errorf("failed to initialize Docker CLI: %w", err)
	}
	defer cli.Client().Close()

	return nil
}

// createComposeService creates a new compose service connected to Docker
func (h *DeployHandler) createComposeService(ctx context.Context) (api.Compose, *dockercli.DockerCli, error) {
	cli, err := dockercli.NewDockerCli()
	if err != nil {
		return nil, nil, fmt.Errorf("failed to create Docker CLI: %w", err)
	}

	opts := flags.NewClientOptions()
	if err := cli.Initialize(opts); err != nil {
		cli.Client().Close()
		return nil, nil, fmt.Errorf("failed to initialize Docker CLI: %w", err)
	}

	composeService := compose.NewComposeService(cli)
	return composeService, cli, nil
}

// loadProject loads a compose project from file content
func (h *DeployHandler) loadProject(ctx context.Context, composeFile, projectName string, envVars map[string]string, profiles []string) (*types.Project, error) {
	workingDir := filepath.Dir(composeFile)

	// Build environment variables slice
	var envSlice []string
	for k, v := range envVars {
		envSlice = append(envSlice, fmt.Sprintf("%s=%s", k, v))
	}

	projectOpts, err := cli.NewProjectOptions(
		[]string{composeFile},
		cli.WithWorkingDirectory(workingDir),
		cli.WithName(projectName),
		cli.WithEnv(envSlice),
		cli.WithProfiles(profiles),
		cli.WithDotEnv,
	)
	if err != nil {
		return nil, fmt.Errorf("failed to create project options: %w", err)
	}

	project, err := projectOpts.LoadProject(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to load compose project: %w", err)
	}

	return project, nil
}

// DeployCompose handles the deploy_compose command
func (h *DeployHandler) DeployCompose(ctx context.Context, req DeployComposeRequest) *DeployComposeResult {
	h.log.WithFields(logrus.Fields{
		"deployment_id": req.DeploymentID,
		"project_name":  req.ProjectName,
		"action":        req.Action,
	}).Info("Starting compose deployment (library mode)")

	h.sendProgress(req.DeploymentID, DeployStageStarting, "Starting deployment...")

	// Write compose content to temp file
	composeFile, err := h.writeComposeFile(req.ComposeContent)
	if err != nil {
		return h.failResult(req.DeploymentID, fmt.Sprintf("Failed to write compose file: %v", err))
	}
	defer os.Remove(composeFile)

	var result *DeployComposeResult

	switch req.Action {
	case "up":
		result = h.runComposeUp(ctx, req, composeFile)
	case "down":
		result = h.runComposeDown(ctx, req, composeFile)
	case "restart":
		h.sendProgress(req.DeploymentID, DeployStageExecuting, "Stopping services...")
		downReq := req
		downReq.RemoveVolumes = false
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

// writeComposeFile writes compose content to a temp file
func (h *DeployHandler) writeComposeFile(content string) (string, error) {
	f, err := os.CreateTemp("", "dockmon-compose-*.yml")
	if err != nil {
		return "", fmt.Errorf("failed to create temp file: %w", err)
	}

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

// runComposeUp executes compose up using the library
func (h *DeployHandler) runComposeUp(ctx context.Context, req DeployComposeRequest, composeFile string) *DeployComposeResult {
	h.sendProgress(req.DeploymentID, DeployStageExecuting, "Running compose up...")

	// Create compose service
	h.mu.Lock()
	composeService, cli, err := h.createComposeService(ctx)
	h.mu.Unlock()

	if err != nil {
		return h.failResult(req.DeploymentID, fmt.Sprintf("Failed to create compose service: %v", err))
	}
	defer cli.Client().Close()

	// Load project
	project, err := h.loadProject(ctx, composeFile, req.ProjectName, req.Environment, req.Profiles)
	if err != nil {
		return h.failResult(req.DeploymentID, fmt.Sprintf("Failed to load compose project: %v", err))
	}

	// Remove unnecessary resources (like disabled services)
	project = project.WithoutUnnecessaryResources()

	// Add custom labels for service identification
	for i, s := range project.Services {
		if s.CustomLabels == nil {
			s.CustomLabels = make(types.Labels)
		}
		s.CustomLabels["com.docker.compose.project"] = project.Name
		s.CustomLabels["com.docker.compose.service"] = s.Name
		project.Services[i] = s
	}

	// Execute up
	upOpts := api.UpOptions{
		Create: api.CreateOptions{
			RemoveOrphans: true,
		},
	}

	h.log.WithFields(logrus.Fields{
		"project_name":   req.ProjectName,
		"services_count": len(project.Services),
	}).Info("Executing compose up")

	if err := composeService.Up(ctx, project, upOpts); err != nil {
		h.log.WithError(err).Error("Compose up failed")

		// Attempt cleanup on failure
		h.log.Warn("Deployment failed, attempting cleanup...")
		_ = composeService.Down(ctx, req.ProjectName, api.DownOptions{RemoveOrphans: true})

		return h.failResult(req.DeploymentID, fmt.Sprintf("Compose up failed: %v", err))
	}

	// Wait for health checks if requested
	if req.WaitForHealthy {
		h.sendProgress(req.DeploymentID, DeployStageWaitingHealth, "Waiting for services to be healthy...")
		timeout := req.HealthTimeout
		if timeout <= 0 {
			timeout = 60
		}
		if err := h.waitForHealthy(ctx, composeService, req.ProjectName, timeout); err != nil {
			h.log.WithError(err).Error("Health check failed")
			return h.failResult(req.DeploymentID, fmt.Sprintf("Health check failed: %v", err))
		}
		h.log.Info("All services healthy")
	}

	// Discover containers
	h.sendProgress(req.DeploymentID, DeployStageCompleted, "Discovering containers...")
	services, discoverErr := h.discoverContainers(ctx, req.ProjectName)
	if discoverErr != nil {
		h.log.WithError(discoverErr).Warn("Failed to discover containers after deployment")
		return &DeployComposeResult{
			DeploymentID: req.DeploymentID,
			Success:      true,
			Services:     make(map[string]ServiceResult),
			Error:        fmt.Sprintf("Deployment succeeded but container discovery failed: %v", discoverErr),
		}
	}

	return h.analyzeServiceStatus(req.DeploymentID, services)
}

// runComposeDown executes compose down using the library
func (h *DeployHandler) runComposeDown(ctx context.Context, req DeployComposeRequest, composeFile string) *DeployComposeResult {
	h.sendProgress(req.DeploymentID, DeployStageExecuting, "Running compose down...")

	// Create compose service
	h.mu.Lock()
	composeService, cli, err := h.createComposeService(ctx)
	h.mu.Unlock()

	if err != nil {
		return h.failResult(req.DeploymentID, fmt.Sprintf("Failed to create compose service: %v", err))
	}
	defer cli.Client().Close()

	// Execute down
	downOpts := api.DownOptions{
		RemoveOrphans: true,
		Volumes:       req.RemoveVolumes,
	}

	if req.RemoveVolumes {
		h.log.Warn("Removing volumes as requested (destructive operation)")
	}

	h.log.WithField("project_name", req.ProjectName).Info("Executing compose down")

	if err := composeService.Down(ctx, req.ProjectName, downOpts); err != nil {
		h.log.WithError(err).Error("Compose down failed")
		return h.failResult(req.DeploymentID, fmt.Sprintf("Compose down failed: %v", err))
	}

	h.log.WithField("deployment_id", req.DeploymentID).Info("Compose down completed successfully")

	return &DeployComposeResult{
		DeploymentID: req.DeploymentID,
		Success:      true,
		Services:     make(map[string]ServiceResult),
	}
}

// waitForHealthy polls container status until all are healthy or timeout
func (h *DeployHandler) waitForHealthy(ctx context.Context, composeService api.Compose, projectName string, timeoutSecs int) error {
	h.log.WithFields(logrus.Fields{
		"project_name": projectName,
		"timeout_secs": timeoutSecs,
	}).Info("Waiting for services to be healthy")

	deadline := time.Now().Add(time.Duration(timeoutSecs) * time.Second)
	pollInterval := 2 * time.Second

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		// Get container status via compose ps
		containers, err := composeService.Ps(ctx, projectName, api.PsOptions{All: true})
		if err != nil {
			h.log.WithError(err).Debug("Failed to get container status, retrying...")
			time.Sleep(pollInterval)
			continue
		}

		if len(containers) == 0 {
			h.log.Debug("No containers found yet, retrying...")
			time.Sleep(pollInterval)
			continue
		}

		// Check health status
		allHealthy := true
		var unhealthyServices []string

		for _, c := range containers {
			healthy := h.isContainerHealthy(c)
			if !healthy {
				allHealthy = false
				unhealthyServices = append(unhealthyServices, c.Service)
			}
		}

		if allHealthy {
			h.log.WithField("container_count", len(containers)).Info("All services are healthy")
			return nil
		}

		h.log.WithFields(logrus.Fields{
			"unhealthy_services": unhealthyServices,
			"total_services":     len(containers),
		}).Debug("Waiting for services to be healthy...")

		time.Sleep(pollInterval)
	}

	// Timeout - get final status
	containers, _ := composeService.Ps(ctx, projectName, api.PsOptions{All: true})
	var unhealthyDetails []string
	for _, c := range containers {
		if !h.isContainerHealthy(c) {
			detail := fmt.Sprintf("%s: state=%s, health=%s", c.Service, c.State, c.Health)
			unhealthyDetails = append(unhealthyDetails, detail)
		}
	}

	return fmt.Errorf("timeout after %d seconds waiting for healthy services. Unhealthy: %s",
		timeoutSecs, strings.Join(unhealthyDetails, "; "))
}

// isContainerHealthy checks if a container is healthy
func (h *DeployHandler) isContainerHealthy(c api.ContainerSummary) bool {
	state := strings.ToLower(c.State)
	health := strings.ToLower(c.Health)

	// If container has a health check
	if health != "" {
		return health == "healthy"
	}

	// No health check - just check if running
	return state == "running"
}

// discoverContainers finds containers created by compose
func (h *DeployHandler) discoverContainers(ctx context.Context, projectName string) (map[string]ServiceResult, error) {
	containers, err := h.dockerClient.ListAllContainers(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to list containers: %w", err)
	}

	services := make(map[string]ServiceResult)

	for _, c := range containers {
		if c.Labels["com.docker.compose.project"] != projectName {
			continue
		}

		serviceName := c.Labels["com.docker.compose.service"]
		if serviceName == "" {
			serviceName = "unknown"
		}

		containerName := ""
		if len(c.Names) > 0 {
			containerName = strings.TrimPrefix(c.Names[0], "/")
		}

		shortID := c.ID
		if len(shortID) > 12 {
			shortID = shortID[:12]
		}

		status := c.State
		if status == "" {
			status = c.Status
		}

		services[serviceName] = ServiceResult{
			ContainerID:   shortID,
			ContainerName: containerName,
			Image:         c.Image,
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

// analyzeServiceStatus checks each service and determines success/partial/failure
func (h *DeployHandler) analyzeServiceStatus(deploymentID string, services map[string]ServiceResult) *DeployComposeResult {
	var runningServices []string
	var failedServices []string
	var failedErrors []string

	for serviceName, service := range services {
		if isServiceHealthy(service.Status) {
			runningServices = append(runningServices, serviceName)
		} else {
			failedServices = append(failedServices, serviceName)
			errMsg := fmt.Sprintf("%s: %s", serviceName, service.Status)
			if service.Error != "" {
				errMsg = fmt.Sprintf("%s: %s (%s)", serviceName, service.Status, service.Error)
			}
			failedErrors = append(failedErrors, errMsg)
		}
	}

	// All services running
	if len(failedServices) == 0 && len(runningServices) > 0 {
		h.log.WithFields(logrus.Fields{
			"deployment_id":  deploymentID,
			"services_count": len(services),
		}).Info("Compose deployment completed successfully - all services running")

		return &DeployComposeResult{
			DeploymentID: deploymentID,
			Success:      true,
			Services:     services,
		}
	}

	// Partial success
	if len(runningServices) > 0 && len(failedServices) > 0 {
		h.log.WithFields(logrus.Fields{
			"deployment_id":    deploymentID,
			"running_services": runningServices,
			"failed_services":  failedServices,
		}).Warn("Compose deployment partial success - some services failed")

		errorMsg := fmt.Sprintf("Partial deployment: %d/%d services running. Failed: %s",
			len(runningServices), len(services), strings.Join(failedErrors, "; "))

		return &DeployComposeResult{
			DeploymentID:   deploymentID,
			Success:        false,
			PartialSuccess: true,
			Services:       services,
			FailedServices: failedServices,
			Error:          errorMsg,
		}
	}

	// All failed
	if len(runningServices) == 0 && len(failedServices) > 0 {
		h.log.WithFields(logrus.Fields{
			"deployment_id":   deploymentID,
			"failed_services": failedServices,
		}).Error("Compose deployment failed - no services running")

		errorMsg := fmt.Sprintf("All services failed to start: %s", strings.Join(failedErrors, "; "))

		return &DeployComposeResult{
			DeploymentID:   deploymentID,
			Success:        false,
			PartialSuccess: false,
			Services:       services,
			FailedServices: failedServices,
			Error:          errorMsg,
		}
	}

	// No services (shouldn't happen)
	h.log.WithField("deployment_id", deploymentID).Warn("No services discovered after compose up")
	return &DeployComposeResult{
		DeploymentID: deploymentID,
		Success:      true,
		Services:     services,
	}
}

// isServiceHealthy checks if a service status indicates healthy/running state
func isServiceHealthy(status string) bool {
	status = strings.ToLower(status)
	if status == "running" || status == "up" || strings.HasPrefix(status, "up ") {
		return true
	}
	if strings.Contains(status, "healthy") && !strings.Contains(status, "unhealthy") {
		return true
	}
	return false
}

// sendProgress sends a deploy progress event
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

// failResult creates a failure result
func (h *DeployHandler) failResult(deploymentID, errorMsg string) *DeployComposeResult {
	h.sendProgress(deploymentID, DeployStageFailed, errorMsg)

	return &DeployComposeResult{
		DeploymentID: deploymentID,
		Success:      false,
		Error:        errorMsg,
	}
}

// HasComposeSupport returns true (library always available once handler is created)
func (h *DeployHandler) HasComposeSupport() bool {
	return true
}

// GetComposeCommand returns description of compose method
func (h *DeployHandler) GetComposeCommand() string {
	return "Docker Compose Go library (embedded)"
}
