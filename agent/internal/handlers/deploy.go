package handlers

import (
	"context"
	"fmt"
	"sync"

	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/darthnorse/dockmon-shared/compose"
	sharedDocker "github.com/darthnorse/dockmon-shared/docker"
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
// This wraps the shared compose.DeployRequest for backward compatibility
type DeployComposeRequest struct {
	DeploymentID        string                       `json:"deployment_id"`
	ProjectName         string                       `json:"project_name"`
	ComposeContent      string                       `json:"compose_content"`
	Environment         map[string]string            `json:"environment,omitempty"`
	Action              string                       `json:"action"`         // "up", "down", "restart"
	RemoveVolumes       bool                         `json:"remove_volumes"` // Only for "down" action, default false
	ForceRecreate       bool                         `json:"force_recreate,omitempty"` // Force recreate containers
	PullImages          bool                         `json:"pull_images,omitempty"`    // Pull images before starting
	Profiles            []string                     `json:"profiles,omitempty"`
	WaitForHealthy      bool                         `json:"wait_for_healthy,omitempty"`
	HealthTimeout       int                          `json:"health_timeout,omitempty"`
	RegistryCredentials []compose.RegistryCredential `json:"registry_credentials,omitempty"`
}

// DeployComposeResult is sent from agent to backend on completion
// This wraps the shared compose.DeployResult for backward compatibility
type DeployComposeResult struct {
	DeploymentID   string                          `json:"deployment_id"`
	Success        bool                            `json:"success"`
	PartialSuccess bool                            `json:"partial_success,omitempty"`
	Services       map[string]compose.ServiceResult `json:"services,omitempty"`
	FailedServices []string                        `json:"failed_services,omitempty"`
	Error          string                          `json:"error,omitempty"`
}

// NewDeployHandler creates a new deploy handler using the Docker Compose Go library
func NewDeployHandler(
	ctx context.Context,
	dockerClient *docker.Client,
	log *logrus.Logger,
	sendEvent func(string, interface{}) error,
) (*DeployHandler, error) {
	// Test that we can create a compose service (validates library availability)
	if err := compose.TestComposeLibrary(); err != nil {
		return nil, fmt.Errorf("Docker Compose library not available: %w", err)
	}

	log.Info("Deploy handler initialized using Docker Compose Go library")

	return &DeployHandler{
		dockerClient: dockerClient,
		log:          log,
		sendEvent:    sendEvent,
	}, nil
}

// DeployCompose handles the deploy_compose command
func (h *DeployHandler) DeployCompose(ctx context.Context, req DeployComposeRequest) *DeployComposeResult {
	h.log.WithFields(logrus.Fields{
		"deployment_id": req.DeploymentID,
		"project_name":  req.ProjectName,
		"action":        req.Action,
	}).Info("Starting compose deployment (library mode)")

	h.sendProgress(req.DeploymentID, compose.DeployStageStarting, "Starting deployment...")

	// Create a Docker SDK client from the agent's internal client
	// We use local socket since the agent always runs on the target host
	dockerClient, err := sharedDocker.CreateLocalClient()
	if err != nil {
		return h.failResult(req.DeploymentID, fmt.Sprintf("Failed to create Docker client: %v", err))
	}
	defer dockerClient.Close()

	// Create shared compose service with progress callback
	svc := compose.NewService(dockerClient, h.log, compose.WithProgressCallback(func(event compose.ProgressEvent) {
		// Forward progress to WebSocket
		h.sendProgress(req.DeploymentID, string(event.Stage), event.Message)
	}))

	// Convert request to shared type
	sharedReq := compose.DeployRequest{
		DeploymentID:        req.DeploymentID,
		ProjectName:         req.ProjectName,
		ComposeYAML:         req.ComposeContent,
		Environment:         req.Environment,
		Profiles:            req.Profiles,
		Action:              req.Action,
		RemoveVolumes:       req.RemoveVolumes,
		ForceRecreate:       req.ForceRecreate,
		PullImages:          req.PullImages,
		WaitForHealthy:      req.WaitForHealthy,
		HealthTimeout:       req.HealthTimeout,
		RegistryCredentials: req.RegistryCredentials,
	}

	// Execute deployment using shared package
	result := svc.Deploy(ctx, sharedReq)

	// Convert result back to agent format
	return h.convertResult(result)
}

// convertResult converts shared compose result to agent format
func (h *DeployHandler) convertResult(result *compose.DeployResult) *DeployComposeResult {
	agentResult := &DeployComposeResult{
		DeploymentID:   result.DeploymentID,
		Success:        result.Success,
		PartialSuccess: result.PartialSuccess,
		Services:       result.Services,
		FailedServices: result.FailedServices,
	}

	if result.Error != nil {
		agentResult.Error = result.Error.Message
	}

	return agentResult
}

// sendProgress sends a deploy progress event
func (h *DeployHandler) sendProgress(deploymentID, stage, message string) {
	progress := map[string]interface{}{
		"deployment_id": deploymentID,
		"stage":         stage,
		"message":       message,
	}

	if err := h.sendEvent("deploy_progress", progress); err != nil {
		h.log.WithField("error", err.Error()).Warn("Failed to send deploy progress")
	}
}

// failResult creates a failure result
func (h *DeployHandler) failResult(deploymentID, errorMsg string) *DeployComposeResult {
	h.sendProgress(deploymentID, compose.DeployStageFailed, errorMsg)

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
	return compose.GetComposeCommand()
}
