//go:build integration

package handlers

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/sirupsen/logrus"
)

// Integration tests for Agent Native Compose Deployments (Phase 3)
// These tests require Docker and docker-compose to be available.
//
// To run these tests:
//   go test -tags=integration -v ./internal/handlers/...
//
// Or with verbose output:
//   go test -tags=integration -v -run Integration ./internal/handlers/...

func skipIfNoDocker(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("docker"); err != nil {
		t.Skip("Docker not available, skipping integration test")
	}
}

func skipIfNoCompose(t *testing.T) {
	t.Helper()
	// Check for docker compose (v2)
	cmd := exec.Command("docker", "compose", "version")
	if err := cmd.Run(); err != nil {
		// Check for docker-compose (v1)
		if _, err := exec.LookPath("docker-compose"); err != nil {
			t.Skip("Docker Compose not available, skipping integration test")
		}
	}
}

func createTestHandler(t *testing.T) *DeployHandler {
	t.Helper()

	ctx := context.Background()
	log := logrus.NewEntry(logrus.New())

	// Mock sendEvent - collect events for verification
	events := make([]map[string]interface{}, 0)
	sendEvent := func(msgType string, payload interface{}) error {
		event := map[string]interface{}{
			"type":    msgType,
			"payload": payload,
		}
		events = append(events, event)
		return nil
	}

	handler := NewDeployHandler(ctx, log, sendEvent)
	if handler == nil {
		t.Fatal("Failed to create deploy handler")
	}

	return handler
}

func TestIntegration_DetectComposeCommand(t *testing.T) {
	skipIfNoDocker(t)
	skipIfNoCompose(t)

	ctx := context.Background()
	cmd := detectComposeCommand(ctx)

	if cmd == nil {
		t.Fatal("detectComposeCommand returned nil, but Docker Compose is available")
	}

	t.Logf("Detected compose command: %v", cmd)
}

func TestIntegration_ComposePs(t *testing.T) {
	skipIfNoDocker(t)
	skipIfNoCompose(t)

	handler := createTestHandler(t)
	ctx := context.Background()

	// Create a temporary compose file
	composeContent := `
services:
  test-nginx:
    image: nginx:alpine
    container_name: dockmon-test-nginx
`
	tmpFile, err := os.CreateTemp("", "compose-*.yml")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(tmpFile.Name())

	if _, err := tmpFile.WriteString(composeContent); err != nil {
		t.Fatal(err)
	}
	tmpFile.Close()

	projectName := "dockmon-integration-test"

	// Start the test container
	args := append([]string{}, handler.composeCmd[1:]...)
	args = append(args, "-f", tmpFile.Name(), "-p", projectName, "up", "-d")
	_, _, err = handler.runCompose(ctx, nil, args...)
	if err != nil {
		t.Fatalf("Failed to start test container: %v", err)
	}

	// Cleanup at the end
	defer func() {
		cleanupArgs := append([]string{}, handler.composeCmd[1:]...)
		cleanupArgs = append(cleanupArgs, "-f", tmpFile.Name(), "-p", projectName, "down", "--remove-orphans")
		handler.runCompose(ctx, nil, cleanupArgs...)
	}()

	// Wait for container to start
	time.Sleep(2 * time.Second)

	// Test ComposePs
	containers, err := handler.ComposePs(ctx, projectName, tmpFile.Name())
	if err != nil {
		t.Fatalf("ComposePs failed: %v", err)
	}

	if len(containers) == 0 {
		t.Fatal("Expected at least one container")
	}

	found := false
	for _, c := range containers {
		t.Logf("Container: ID=%s, Name=%s, Service=%s, State=%s, Status=%s",
			c.ID, c.Name, c.Service, c.State, c.Status)
		if c.Service == "test-nginx" {
			found = true
			if c.State != "running" {
				t.Errorf("Expected container state 'running', got %q", c.State)
			}
		}
	}

	if !found {
		t.Error("test-nginx service not found in compose ps output")
	}
}

func TestIntegration_ComposePsWithProfiles(t *testing.T) {
	skipIfNoDocker(t)
	skipIfNoCompose(t)

	handler := createTestHandler(t)
	ctx := context.Background()

	// Create a compose file with profiles
	composeContent := `
services:
  web:
    image: nginx:alpine
    container_name: dockmon-test-web
  debug:
    image: alpine:latest
    container_name: dockmon-test-debug
    profiles:
      - debug
    command: ["sleep", "infinity"]
`
	tmpFile, err := os.CreateTemp("", "compose-profiles-*.yml")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(tmpFile.Name())

	if _, err := tmpFile.WriteString(composeContent); err != nil {
		t.Fatal(err)
	}
	tmpFile.Close()

	projectName := "dockmon-profiles-test"

	// Start with debug profile
	args := append([]string{}, handler.composeCmd[1:]...)
	args = append(args, "-f", tmpFile.Name(), "-p", projectName, "--profile", "debug", "up", "-d")
	_, _, err = handler.runCompose(ctx, nil, args...)
	if err != nil {
		t.Fatalf("Failed to start containers: %v", err)
	}

	// Cleanup at the end
	defer func() {
		cleanupArgs := append([]string{}, handler.composeCmd[1:]...)
		cleanupArgs = append(cleanupArgs, "-f", tmpFile.Name(), "-p", projectName, "--profile", "debug", "down", "--remove-orphans")
		handler.runCompose(ctx, nil, cleanupArgs...)
	}()

	// Wait for containers to start
	time.Sleep(2 * time.Second)

	// Test ComposePsWithProfiles
	containers, err := handler.ComposePsWithProfiles(ctx, projectName, tmpFile.Name(), []string{"debug"})
	if err != nil {
		t.Fatalf("ComposePsWithProfiles failed: %v", err)
	}

	// Should have both web and debug containers
	foundWeb := false
	foundDebug := false
	for _, c := range containers {
		t.Logf("Container: Service=%s, State=%s", c.Service, c.State)
		if c.Service == "web" {
			foundWeb = true
		}
		if c.Service == "debug" {
			foundDebug = true
		}
	}

	if !foundWeb {
		t.Error("web service not found")
	}
	if !foundDebug {
		t.Error("debug service not found (profile should be active)")
	}
}

func TestIntegration_IsContainerHealthy_RealContainer(t *testing.T) {
	skipIfNoDocker(t)
	skipIfNoCompose(t)

	handler := createTestHandler(t)
	ctx := context.Background()

	// Create a compose file with health check
	composeContent := `
services:
  healthy-nginx:
    image: nginx:alpine
    container_name: dockmon-test-healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost/"]
      interval: 2s
      timeout: 2s
      retries: 3
      start_period: 1s
`
	tmpFile, err := os.CreateTemp("", "compose-health-*.yml")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(tmpFile.Name())

	if _, err := tmpFile.WriteString(composeContent); err != nil {
		t.Fatal(err)
	}
	tmpFile.Close()

	projectName := "dockmon-health-test"

	// Start container
	args := append([]string{}, handler.composeCmd[1:]...)
	args = append(args, "-f", tmpFile.Name(), "-p", projectName, "up", "-d")
	_, _, err = handler.runCompose(ctx, nil, args...)
	if err != nil {
		t.Fatalf("Failed to start container: %v", err)
	}

	// Cleanup at the end
	defer func() {
		cleanupArgs := append([]string{}, handler.composeCmd[1:]...)
		cleanupArgs = append(cleanupArgs, "-f", tmpFile.Name(), "-p", projectName, "down", "--remove-orphans")
		handler.runCompose(ctx, nil, cleanupArgs...)
	}()

	// Wait for health check to pass (with timeout)
	deadline := time.Now().Add(30 * time.Second)
	healthy := false

	for time.Now().Before(deadline) {
		containers, err := handler.ComposePs(ctx, projectName, tmpFile.Name())
		if err != nil {
			time.Sleep(1 * time.Second)
			continue
		}

		for _, c := range containers {
			if c.Service == "healthy-nginx" {
				t.Logf("Container status: State=%s, Status=%s, Health=%s", c.State, c.Status, c.Health)
				if handler.isContainerHealthy(c) {
					healthy = true
					break
				}
			}
		}

		if healthy {
			break
		}
		time.Sleep(1 * time.Second)
	}

	if !healthy {
		t.Error("Container did not become healthy within timeout")
	}
}

func TestIntegration_WaitForHealthy(t *testing.T) {
	skipIfNoDocker(t)
	skipIfNoCompose(t)

	handler := createTestHandler(t)
	ctx := context.Background()

	// Create a compose file with health check
	composeContent := `
services:
  wait-nginx:
    image: nginx:alpine
    container_name: dockmon-test-wait
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost/"]
      interval: 2s
      timeout: 2s
      retries: 3
      start_period: 1s
`
	tmpFile, err := os.CreateTemp("", "compose-wait-*.yml")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(tmpFile.Name())

	if _, err := tmpFile.WriteString(composeContent); err != nil {
		t.Fatal(err)
	}
	tmpFile.Close()

	projectName := "dockmon-wait-test"

	// Start container
	args := append([]string{}, handler.composeCmd[1:]...)
	args = append(args, "-f", tmpFile.Name(), "-p", projectName, "up", "-d")
	_, _, err = handler.runCompose(ctx, nil, args...)
	if err != nil {
		t.Fatalf("Failed to start container: %v", err)
	}

	// Cleanup at the end
	defer func() {
		cleanupArgs := append([]string{}, handler.composeCmd[1:]...)
		cleanupArgs = append(cleanupArgs, "-f", tmpFile.Name(), "-p", projectName, "down", "--remove-orphans")
		handler.runCompose(ctx, nil, cleanupArgs...)
	}()

	// Test waitForHealthy
	err = handler.waitForHealthy(ctx, projectName, tmpFile.Name(), 30, nil)
	if err != nil {
		t.Errorf("waitForHealthy failed: %v", err)
	}
}

func TestIntegration_WaitForHealthy_Timeout(t *testing.T) {
	skipIfNoDocker(t)
	skipIfNoCompose(t)

	handler := createTestHandler(t)
	ctx := context.Background()

	// Create a compose file with a health check that will fail
	composeContent := `
services:
  unhealthy:
    image: alpine:latest
    container_name: dockmon-test-unhealthy
    command: ["sleep", "infinity"]
    healthcheck:
      test: ["CMD", "false"]
      interval: 1s
      timeout: 1s
      retries: 1
      start_period: 0s
`
	tmpFile, err := os.CreateTemp("", "compose-unhealthy-*.yml")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(tmpFile.Name())

	if _, err := tmpFile.WriteString(composeContent); err != nil {
		t.Fatal(err)
	}
	tmpFile.Close()

	projectName := "dockmon-unhealthy-test"

	// Start container
	args := append([]string{}, handler.composeCmd[1:]...)
	args = append(args, "-f", tmpFile.Name(), "-p", projectName, "up", "-d")
	_, _, err = handler.runCompose(ctx, nil, args...)
	if err != nil {
		t.Fatalf("Failed to start container: %v", err)
	}

	// Cleanup at the end
	defer func() {
		cleanupArgs := append([]string{}, handler.composeCmd[1:]...)
		cleanupArgs = append(cleanupArgs, "-f", tmpFile.Name(), "-p", projectName, "down", "--remove-orphans")
		handler.runCompose(ctx, nil, cleanupArgs...)
	}()

	// Test waitForHealthy - should timeout
	err = handler.waitForHealthy(ctx, projectName, tmpFile.Name(), 5, nil)
	if err == nil {
		t.Error("waitForHealthy should have timed out but succeeded")
	}
	if !strings.Contains(err.Error(), "timeout") {
		t.Errorf("Expected timeout error, got: %v", err)
	}
}

func TestIntegration_MapContainerStateToServiceStatus_RealContainers(t *testing.T) {
	skipIfNoDocker(t)
	skipIfNoCompose(t)

	handler := createTestHandler(t)
	ctx := context.Background()

	// Create a compose file with multiple containers in different states
	composeContent := `
services:
  running:
    image: nginx:alpine
    container_name: dockmon-test-running
  healthy:
    image: nginx:alpine
    container_name: dockmon-test-healthy-map
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost/"]
      interval: 2s
      timeout: 2s
      retries: 3
`
	tmpFile, err := os.CreateTemp("", "compose-states-*.yml")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(tmpFile.Name())

	if _, err := tmpFile.WriteString(composeContent); err != nil {
		t.Fatal(err)
	}
	tmpFile.Close()

	projectName := "dockmon-states-test"

	// Start containers
	args := append([]string{}, handler.composeCmd[1:]...)
	args = append(args, "-f", tmpFile.Name(), "-p", projectName, "up", "-d")
	_, _, err = handler.runCompose(ctx, nil, args...)
	if err != nil {
		t.Fatalf("Failed to start containers: %v", err)
	}

	// Cleanup at the end
	defer func() {
		cleanupArgs := append([]string{}, handler.composeCmd[1:]...)
		cleanupArgs = append(cleanupArgs, "-f", tmpFile.Name(), "-p", projectName, "down", "--remove-orphans")
		handler.runCompose(ctx, nil, cleanupArgs...)
	}()

	// Wait for containers to be ready
	time.Sleep(3 * time.Second)

	// Get container states
	containers, err := handler.ComposePs(ctx, projectName, tmpFile.Name())
	if err != nil {
		t.Fatalf("ComposePs failed: %v", err)
	}

	for _, c := range containers {
		status := handler.mapContainerStateToServiceStatus(c)
		t.Logf("Service %s: State=%s, Status=%s, Health=%s -> mapped to %s",
			c.Service, c.State, c.Status, c.Health, status)

		// Verify running containers map to "running" or "starting" (health check might still be running)
		if c.State == "running" {
			if status != "running" && status != "starting" {
				t.Errorf("Expected running container to map to 'running' or 'starting', got %q", status)
			}
		}
	}
}

// TestIntegration_ServiceProgressJson tests that ServiceStatus serializes correctly
func TestIntegration_ServiceProgressJson(t *testing.T) {
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
