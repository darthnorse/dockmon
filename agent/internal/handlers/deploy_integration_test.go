//go:build integration

package handlers

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/config"
	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/docker/compose/v2/pkg/api"
	"github.com/sirupsen/logrus"
)

// Integration tests for Agent Native Compose Deployments using Docker Compose Go library
// These tests require Docker to be available.
//
// To run these tests:
//   go test -tags=integration -v ./internal/handlers/...
//
// Or with verbose output:
//   go test -tags=integration -v -run Integration ./internal/handlers/...

func skipIfNoDocker(t *testing.T) {
	t.Helper()
	// Try to create a docker client - if it fails, Docker is not available
	cfg := &config.Config{}
	log := logrus.New()
	log.SetLevel(logrus.WarnLevel)
	client, err := docker.NewClient(cfg, log)
	if err != nil {
		t.Skipf("Docker not available: %v", err)
	}
	client.Close()
}

func createTestHandler(t *testing.T) (*DeployHandler, *docker.Client) {
	t.Helper()

	ctx := context.Background()
	log := logrus.New()
	log.SetLevel(logrus.DebugLevel)

	// Create Docker client
	cfg := &config.Config{}
	dockerClient, err := docker.NewClient(cfg, log)
	if err != nil {
		t.Fatalf("Failed to create Docker client: %v", err)
	}

	// Mock sendEvent - collect events for verification
	events := make([]map[string]interface{}, 0)
	sendEvent := func(msgType string, payload interface{}) error {
		event := map[string]interface{}{
			"type":    msgType,
			"payload": payload,
		}
		events = append(events, event)
		t.Logf("Event: type=%s", msgType)
		return nil
	}

	// Use temp directory for test stacks
	stacksDir := t.TempDir()

	handler, err := NewDeployHandler(ctx, dockerClient, log, sendEvent, stacksDir)
	if err != nil {
		dockerClient.Close()
		t.Fatalf("Failed to create deploy handler: %v", err)
	}

	return handler, dockerClient
}

func TestIntegration_DeployHandlerCreation(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	// Verify handler reports compose support
	if !handler.HasComposeSupport() {
		t.Error("Handler should report compose support")
	}

	cmd := handler.GetComposeCommand()
	if cmd != "Docker Compose Go library (embedded)" {
		t.Errorf("Expected 'Docker Compose Go library (embedded)', got %q", cmd)
	}

	t.Logf("Deploy handler created successfully, compose method: %s", cmd)
}

func TestIntegration_DeployComposeUp(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	ctx := context.Background()
	projectName := "dockmon-integration-test-up"

	// Simple compose file with nginx
	composeContent := `
services:
  web:
    image: nginx:alpine
    container_name: dockmon-test-web
`

	// Cleanup at the end
	defer func() {
		cleanupReq := DeployComposeRequest{
			DeploymentID:  "cleanup-" + projectName,
			ProjectName:   projectName,
			ComposeContent: composeContent,
			Action:        "down",
			RemoveVolumes: true,
		}
		handler.DeployCompose(ctx, cleanupReq)
	}()

	// Deploy
	req := DeployComposeRequest{
		DeploymentID:   "test-up-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "up",
	}

	result := handler.DeployCompose(ctx, req)

	if !result.Success {
		t.Fatalf("Deploy failed: %s", result.Error)
	}

	// Verify service was created
	if len(result.Services) == 0 {
		t.Error("Expected at least one service in result")
	}

	webService, ok := result.Services["web"]
	if !ok {
		t.Error("Expected 'web' service in results")
	} else {
		t.Logf("Web service: ID=%s, Name=%s, Status=%s",
			webService.ContainerID, webService.ContainerName, webService.Status)

		if webService.ContainerID == "" {
			t.Error("Container ID should not be empty")
		}
		if len(webService.ContainerID) != 12 {
			t.Errorf("Container ID should be 12 chars (short format), got %d", len(webService.ContainerID))
		}
	}
}

func TestIntegration_DeployComposeDown(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	ctx := context.Background()
	projectName := "dockmon-integration-test-down"

	composeContent := `
services:
  web:
    image: nginx:alpine
`

	// First, deploy
	upReq := DeployComposeRequest{
		DeploymentID:   "test-up-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "up",
	}

	upResult := handler.DeployCompose(ctx, upReq)
	if !upResult.Success {
		t.Fatalf("Deploy up failed: %s", upResult.Error)
	}

	// Now tear down
	downReq := DeployComposeRequest{
		DeploymentID:   "test-down-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "down",
		RemoveVolumes:  true,
	}

	downResult := handler.DeployCompose(ctx, downReq)

	if !downResult.Success {
		t.Fatalf("Deploy down failed: %s", downResult.Error)
	}

	t.Log("Compose down completed successfully")
}

func TestIntegration_DeployComposeRestart(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	ctx := context.Background()
	projectName := "dockmon-integration-test-restart"

	composeContent := `
services:
  web:
    image: nginx:alpine
`

	// Cleanup at the end
	defer func() {
		cleanupReq := DeployComposeRequest{
			DeploymentID:   "cleanup-" + projectName,
			ProjectName:    projectName,
			ComposeContent: composeContent,
			Action:         "down",
			RemoveVolumes:  true,
		}
		handler.DeployCompose(ctx, cleanupReq)
	}()

	// First, deploy
	upReq := DeployComposeRequest{
		DeploymentID:   "test-up-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "up",
	}

	upResult := handler.DeployCompose(ctx, upReq)
	if !upResult.Success {
		t.Fatalf("Deploy up failed: %s", upResult.Error)
	}

	// Get initial container ID
	initialID := ""
	if webService, ok := upResult.Services["web"]; ok {
		initialID = webService.ContainerID
	}

	// Restart
	restartReq := DeployComposeRequest{
		DeploymentID:   "test-restart-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "restart",
	}

	restartResult := handler.DeployCompose(ctx, restartReq)

	if !restartResult.Success {
		t.Fatalf("Restart failed: %s", restartResult.Error)
	}

	// Container ID may or may not change depending on compose behavior
	t.Logf("Restart completed. Initial ID: %s", initialID)
	if webService, ok := restartResult.Services["web"]; ok {
		t.Logf("After restart ID: %s, Status: %s", webService.ContainerID, webService.Status)
	}
}

func TestIntegration_DeployComposeWithProfiles(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	ctx := context.Background()
	projectName := "dockmon-integration-test-profiles"

	// Compose file with profiles
	composeContent := `
services:
  web:
    image: nginx:alpine
  debug:
    image: alpine:latest
    profiles:
      - debug
    command: ["sleep", "infinity"]
`

	// Cleanup at the end
	defer func() {
		cleanupReq := DeployComposeRequest{
			DeploymentID:   "cleanup-" + projectName,
			ProjectName:    projectName,
			ComposeContent: composeContent,
			Action:         "down",
			RemoveVolumes:  true,
			Profiles:       []string{"debug"},
		}
		handler.DeployCompose(ctx, cleanupReq)
	}()

	// Deploy with debug profile
	req := DeployComposeRequest{
		DeploymentID:   "test-profiles-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "up",
		Profiles:       []string{"debug"},
	}

	result := handler.DeployCompose(ctx, req)

	if !result.Success {
		t.Fatalf("Deploy failed: %s", result.Error)
	}

	// Should have both web and debug services
	if _, ok := result.Services["web"]; !ok {
		t.Error("Expected 'web' service")
	}
	if _, ok := result.Services["debug"]; !ok {
		t.Error("Expected 'debug' service (profile should be active)")
	}

	t.Logf("Deployed %d services with profiles", len(result.Services))
}

func TestIntegration_DeployComposeWithHealthCheck(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	ctx := context.Background()
	projectName := "dockmon-integration-test-health"

	// Compose file with health check
	composeContent := `
services:
  web:
    image: nginx:alpine
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost/"]
      interval: 2s
      timeout: 2s
      retries: 3
      start_period: 1s
`

	// Cleanup at the end
	defer func() {
		cleanupReq := DeployComposeRequest{
			DeploymentID:   "cleanup-" + projectName,
			ProjectName:    projectName,
			ComposeContent: composeContent,
			Action:         "down",
			RemoveVolumes:  true,
		}
		handler.DeployCompose(ctx, cleanupReq)
	}()

	// Deploy with health check waiting
	req := DeployComposeRequest{
		DeploymentID:   "test-health-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "up",
		WaitForHealthy: true,
		HealthTimeout:  30,
	}

	result := handler.DeployCompose(ctx, req)

	if !result.Success {
		t.Fatalf("Deploy failed: %s", result.Error)
	}

	webService, ok := result.Services["web"]
	if !ok {
		t.Fatal("Expected 'web' service")
	}

	t.Logf("Service deployed with health check, status: %s", webService.Status)
}

func TestIntegration_DeployComposeHealthTimeout(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	ctx := context.Background()
	projectName := "dockmon-integration-test-health-timeout"

	// Compose file with a health check that will fail
	composeContent := `
services:
  unhealthy:
    image: alpine:latest
    command: ["sleep", "infinity"]
    healthcheck:
      test: ["CMD", "false"]
      interval: 1s
      timeout: 1s
      retries: 1
      start_period: 0s
`

	// Cleanup at the end
	defer func() {
		cleanupReq := DeployComposeRequest{
			DeploymentID:   "cleanup-" + projectName,
			ProjectName:    projectName,
			ComposeContent: composeContent,
			Action:         "down",
			RemoveVolumes:  true,
		}
		handler.DeployCompose(ctx, cleanupReq)
	}()

	// Deploy with health check waiting - should timeout
	req := DeployComposeRequest{
		DeploymentID:   "test-health-timeout-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "up",
		WaitForHealthy: true,
		HealthTimeout:  5, // Short timeout
	}

	result := handler.DeployCompose(ctx, req)

	// Should fail due to health timeout
	if result.Success {
		t.Error("Expected deployment to fail due to health timeout")
	}

	if !strings.Contains(result.Error, "timeout") && !strings.Contains(result.Error, "Health") {
		t.Errorf("Expected timeout-related error, got: %s", result.Error)
	}

	t.Logf("Correctly failed with: %s", result.Error)
}

func TestIntegration_IsContainerHealthy(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	// Test the isContainerHealthy method with various container states
	tests := []struct {
		name     string
		c        api.ContainerSummary
		expected bool
	}{
		{
			name:     "healthy with health field",
			c:        api.ContainerSummary{State: "running", Health: "healthy"},
			expected: true,
		},
		{
			name:     "unhealthy with health field",
			c:        api.ContainerSummary{State: "running", Health: "unhealthy"},
			expected: false,
		},
		{
			name:     "starting with health field",
			c:        api.ContainerSummary{State: "running", Health: "starting"},
			expected: false,
		},
		{
			name:     "running no health check",
			c:        api.ContainerSummary{State: "running"},
			expected: true,
		},
		{
			name:     "exited no health check",
			c:        api.ContainerSummary{State: "exited"},
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := handler.isContainerHealthy(tt.c)
			if result != tt.expected {
				t.Errorf("isContainerHealthy() = %v, expected %v", result, tt.expected)
			}
		})
	}
}

func TestIntegration_PartialDeploymentFailure(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	ctx := context.Background()
	projectName := "dockmon-integration-test-partial"

	// Compose file where one service will fail (invalid image)
	composeContent := `
services:
  web:
    image: nginx:alpine
  broken:
    image: this-image-does-not-exist-12345:latest
`

	// Cleanup at the end
	defer func() {
		cleanupReq := DeployComposeRequest{
			DeploymentID:   "cleanup-" + projectName,
			ProjectName:    projectName,
			ComposeContent: composeContent,
			Action:         "down",
			RemoveVolumes:  true,
		}
		handler.DeployCompose(ctx, cleanupReq)
	}()

	// Deploy - should have partial failure
	req := DeployComposeRequest{
		DeploymentID:   "test-partial-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "up",
	}

	result := handler.DeployCompose(ctx, req)

	// The compose library may handle this differently - it might fail entirely
	// or succeed partially. Log the actual behavior.
	t.Logf("Partial deployment result: Success=%v, PartialSuccess=%v, Error=%s",
		result.Success, result.PartialSuccess, result.Error)
	t.Logf("Services: %+v", result.Services)
	t.Logf("Failed services: %v", result.FailedServices)
}

func TestIntegration_DeployComposeWithEnvVars(t *testing.T) {
	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	ctx := context.Background()
	projectName := "dockmon-integration-test-env"

	// Compose file using environment variables
	composeContent := `
services:
  web:
    image: ${IMAGE_NAME:-nginx:alpine}
    environment:
      - TEST_VAR=${TEST_VAR:-default}
`

	// Cleanup at the end
	defer func() {
		cleanupReq := DeployComposeRequest{
			DeploymentID:   "cleanup-" + projectName,
			ProjectName:    projectName,
			ComposeContent: composeContent,
			Action:         "down",
			RemoveVolumes:  true,
		}
		handler.DeployCompose(ctx, cleanupReq)
	}()

	// Deploy with environment variables
	req := DeployComposeRequest{
		DeploymentID:   "test-env-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "up",
		Environment: map[string]string{
			"IMAGE_NAME": "nginx:alpine",
			"TEST_VAR":   "custom_value",
		},
	}

	result := handler.DeployCompose(ctx, req)

	if !result.Success {
		t.Fatalf("Deploy failed: %s", result.Error)
	}

	t.Logf("Deployed with environment variables, services: %d", len(result.Services))
}

func TestIntegration_ServiceProgressJson(t *testing.T) {
	// Test that ServiceStatus serializes correctly
	services := []ServiceStatus{
		{
			Name:    "web",
			Status:  "running",
			Image:   "nginx:alpine",
			Message: "Container started",
		},
		{
			Name:    "db",
			Status:  "creating",
			Image:   "postgres:15",
			Message: "",
		},
	}

	data, err := json.Marshal(services)
	if err != nil {
		t.Fatalf("Failed to marshal ServiceStatus: %v", err)
	}

	t.Logf("Serialized: %s", string(data))

	// Verify it deserializes correctly
	var parsed []ServiceStatus
	if err := json.Unmarshal(data, &parsed); err != nil {
		t.Fatalf("Failed to unmarshal: %v", err)
	}

	if len(parsed) != 2 {
		t.Errorf("Expected 2 services, got %d", len(parsed))
	}
	if parsed[0].Name != "web" || parsed[0].Status != "running" {
		t.Errorf("First service incorrect: %+v", parsed[0])
	}
}

func TestIntegration_LongRunningDeployment(t *testing.T) {
	if os.Getenv("RUN_LONG_TESTS") != "1" {
		t.Skip("Skipping long-running test (set RUN_LONG_TESTS=1 to enable)")
	}

	skipIfNoDocker(t)

	handler, dockerClient := createTestHandler(t)
	defer dockerClient.Close()

	ctx := context.Background()
	projectName := "dockmon-integration-test-long"

	// Multi-service compose file
	composeContent := `
services:
  web:
    image: nginx:alpine
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost/"]
      interval: 2s
      timeout: 2s
      retries: 3
  redis:
    image: redis:alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      timeout: 2s
      retries: 3
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_PASSWORD: test
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
      timeout: 2s
      retries: 5
`

	// Cleanup at the end
	defer func() {
		cleanupReq := DeployComposeRequest{
			DeploymentID:   "cleanup-" + projectName,
			ProjectName:    projectName,
			ComposeContent: composeContent,
			Action:         "down",
			RemoveVolumes:  true,
		}
		handler.DeployCompose(ctx, cleanupReq)
	}()

	start := time.Now()

	// Deploy with health check waiting
	req := DeployComposeRequest{
		DeploymentID:   "test-long-" + projectName,
		ProjectName:    projectName,
		ComposeContent: composeContent,
		Action:         "up",
		WaitForHealthy: true,
		HealthTimeout:  120,
	}

	result := handler.DeployCompose(ctx, req)

	elapsed := time.Since(start)

	if !result.Success {
		t.Fatalf("Long deployment failed after %v: %s", elapsed, result.Error)
	}

	t.Logf("Long deployment completed in %v with %d services", elapsed, len(result.Services))
	for name, svc := range result.Services {
		t.Logf("  %s: %s (%s)", name, svc.Status, svc.ContainerID)
	}
}
