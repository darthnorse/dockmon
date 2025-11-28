package handlers

import (
	"context"
	"testing"
)

func TestDetectComposeCommand(t *testing.T) {
	ctx := context.Background()

	// Test that detectComposeCommand returns something on a system with compose
	// Note: This test may pass or fail depending on the system setup
	cmd := detectComposeCommand(ctx)

	// On most Docker hosts, this will return either ["docker", "compose"] or ["docker-compose"]
	// On systems without compose, this returns nil
	if cmd != nil {
		// If compose is available, verify it's a valid command structure
		if len(cmd) < 1 {
			t.Errorf("detectComposeCommand returned empty slice, expected at least one element")
		}
	}
	// If cmd is nil, that's OK - compose isn't installed
}

func TestParseComposeError(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected string
	}{
		{
			name:     "empty string",
			input:    "",
			expected: "",
		},
		{
			name:     "short error",
			input:    "Error: image not found",
			expected: "Error: image not found",
		},
		{
			name:     "whitespace only",
			input:    "   \n  \t  ",
			expected: "",
		},
		{
			name:     "multiline with truncation",
			input:    "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10\nline11\nline12\nline13",
			expected: "line4\nline5\nline6\nline7\nline8\nline9\nline10\nline11\nline12\nline13",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := parseComposeError(tt.input)
			if result != tt.expected {
				t.Errorf("parseComposeError(%q) = %q, expected %q", tt.input, result, tt.expected)
			}
		})
	}
}

func TestDeployComposeRequest(t *testing.T) {
	// Test that DeployComposeRequest struct has all required fields
	req := DeployComposeRequest{
		DeploymentID:   "test-deployment-123",
		ProjectName:    "test-project",
		ComposeContent: "services:\n  web:\n    image: nginx:alpine",
		Environment:    map[string]string{"FOO": "bar"},
		Action:         "up",
		RemoveVolumes:  false,
	}

	if req.DeploymentID == "" {
		t.Error("DeploymentID should not be empty")
	}
	if req.ProjectName == "" {
		t.Error("ProjectName should not be empty")
	}
	if req.Action != "up" {
		t.Errorf("Action = %q, expected 'up'", req.Action)
	}
}

func TestDeployComposeResult(t *testing.T) {
	// Test success result
	successResult := DeployComposeResult{
		DeploymentID: "test-123",
		Success:      true,
		Services: map[string]ServiceResult{
			"web": {
				ContainerID:   "abc123def456",
				ContainerName: "test_web_1",
				Image:         "nginx:alpine",
				Status:        "running",
			},
		},
	}

	if !successResult.Success {
		t.Error("Success should be true")
	}
	if len(successResult.Services) != 1 {
		t.Errorf("Services count = %d, expected 1", len(successResult.Services))
	}
	if successResult.Services["web"].ContainerID != "abc123def456" {
		t.Error("ContainerID mismatch")
	}

	// Test failure result
	failResult := DeployComposeResult{
		DeploymentID: "test-456",
		Success:      false,
		Error:        "Image pull failed",
	}

	if failResult.Success {
		t.Error("Success should be false")
	}
	if failResult.Error == "" {
		t.Error("Error should not be empty for failed result")
	}
}

func TestServiceResult(t *testing.T) {
	result := ServiceResult{
		ContainerID:   "123456789012", // 12 chars
		ContainerName: "test_container",
		Image:         "nginx:alpine",
		Status:        "running",
	}

	// Container ID should be 12 chars (short format)
	if len(result.ContainerID) != 12 {
		t.Errorf("ContainerID length = %d, expected 12", len(result.ContainerID))
	}
}

func TestDeployStageConstants(t *testing.T) {
	// Verify stage constants are defined
	stages := []string{
		DeployStageStarting,
		DeployStageExecuting,
		DeployStageCompleted,
		DeployStageFailed,
	}

	for _, stage := range stages {
		if stage == "" {
			t.Errorf("Stage constant should not be empty")
		}
	}

	// Verify uniqueness
	stageSet := make(map[string]bool)
	for _, stage := range stages {
		if stageSet[stage] {
			t.Errorf("Duplicate stage constant: %s", stage)
		}
		stageSet[stage] = true
	}
}

func TestIsServiceHealthy(t *testing.T) {
	tests := []struct {
		name     string
		status   string
		expected bool
	}{
		{"running lowercase", "running", true},
		{"running uppercase", "Running", true},
		{"up status", "up", true},
		{"up with duration", "Up 5 minutes", true},
		{"healthy status", "healthy", true},
		{"running (healthy)", "running (healthy)", true},
		{"unhealthy status", "unhealthy", false},
		{"running (unhealthy)", "running (unhealthy)", false},
		{"exited status", "exited", false},
		{"exited with code", "exited (1)", false},
		{"created status", "created", false},
		{"dead status", "dead", false},
		{"paused status", "paused", false},
		{"empty status", "", false},
		{"restarting status", "restarting", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := isServiceHealthy(tt.status)
			if result != tt.expected {
				t.Errorf("isServiceHealthy(%q) = %v, expected %v", tt.status, result, tt.expected)
			}
		})
	}
}

func TestDeployComposeResultPartialSuccess(t *testing.T) {
	// Test partial success result structure
	result := DeployComposeResult{
		DeploymentID:   "test-123",
		Success:        false,
		PartialSuccess: true,
		Services: map[string]ServiceResult{
			"web": {
				ContainerID:   "abc123def456",
				ContainerName: "test_web_1",
				Image:         "nginx:alpine",
				Status:        "running",
			},
			"db": {
				ContainerID:   "xyz789ghi012",
				ContainerName: "test_db_1",
				Image:         "postgres:15",
				Status:        "exited (1)",
				Error:         "Database initialization failed",
			},
		},
		FailedServices: []string{"db"},
		Error:          "Partial deployment: 1/2 services running. Failed: db: exited (1)",
	}

	// Verify fields
	if result.Success {
		t.Error("Success should be false for partial deployment")
	}
	if !result.PartialSuccess {
		t.Error("PartialSuccess should be true")
	}
	if len(result.FailedServices) != 1 {
		t.Errorf("FailedServices count = %d, expected 1", len(result.FailedServices))
	}
	if result.FailedServices[0] != "db" {
		t.Errorf("FailedServices[0] = %s, expected 'db'", result.FailedServices[0])
	}
	if result.Error == "" {
		t.Error("Error should not be empty for partial deployment")
	}
	if result.Services["db"].Error == "" {
		t.Error("Failed service should have error details")
	}
}

func TestDeployComposeResultFullFailure(t *testing.T) {
	// Test full failure result structure (all services failed)
	result := DeployComposeResult{
		DeploymentID:   "test-456",
		Success:        false,
		PartialSuccess: false,
		Services: map[string]ServiceResult{
			"web": {
				ContainerID:   "abc123def456",
				ContainerName: "test_web_1",
				Image:         "nginx:alpine",
				Status:        "exited (1)",
			},
			"db": {
				ContainerID:   "xyz789ghi012",
				ContainerName: "test_db_1",
				Image:         "postgres:15",
				Status:        "exited (1)",
			},
		},
		FailedServices: []string{"web", "db"},
		Error:          "All services failed to start",
	}

	if result.Success {
		t.Error("Success should be false")
	}
	if result.PartialSuccess {
		t.Error("PartialSuccess should be false for full failure")
	}
	if len(result.FailedServices) != 2 {
		t.Errorf("FailedServices count = %d, expected 2", len(result.FailedServices))
	}
}

// Phase 3 Tests

func TestDeployComposeRequestProfiles(t *testing.T) {
	// Test that profiles are included in request
	req := DeployComposeRequest{
		DeploymentID:   "test-deployment-123",
		ProjectName:    "test-project",
		ComposeContent: "services:\n  web:\n    image: nginx:alpine",
		Action:         "up",
		Profiles:       []string{"dev", "debug"},
	}

	if len(req.Profiles) != 2 {
		t.Errorf("Profiles count = %d, expected 2", len(req.Profiles))
	}
	if req.Profiles[0] != "dev" {
		t.Errorf("Profiles[0] = %q, expected 'dev'", req.Profiles[0])
	}
	if req.Profiles[1] != "debug" {
		t.Errorf("Profiles[1] = %q, expected 'debug'", req.Profiles[1])
	}
}

func TestDeployComposeRequestHealthAware(t *testing.T) {
	// Test health-aware deployment fields
	req := DeployComposeRequest{
		DeploymentID:   "test-deployment-123",
		ProjectName:    "test-project",
		ComposeContent: "services:\n  web:\n    image: nginx:alpine",
		Action:         "up",
		WaitForHealthy: true,
		HealthTimeout:  120,
	}

	if !req.WaitForHealthy {
		t.Error("WaitForHealthy should be true")
	}
	if req.HealthTimeout != 120 {
		t.Errorf("HealthTimeout = %d, expected 120", req.HealthTimeout)
	}
}

func TestDeployStageWaitingHealth(t *testing.T) {
	// Verify the new waiting_for_health stage constant exists
	if DeployStageWaitingHealth != "waiting_for_health" {
		t.Errorf("DeployStageWaitingHealth = %q, expected 'waiting_for_health'", DeployStageWaitingHealth)
	}

	// Verify it's unique among stages
	stages := []string{
		DeployStageStarting,
		DeployStageExecuting,
		DeployStageWaitingHealth,
		DeployStageCompleted,
		DeployStageFailed,
	}

	stageSet := make(map[string]bool)
	for _, stage := range stages {
		if stageSet[stage] {
			t.Errorf("Duplicate stage constant: %s", stage)
		}
		stageSet[stage] = true
	}
}

func TestComposeContainerHealth(t *testing.T) {
	// Test ComposeContainer with Health field
	container := ComposeContainer{
		ID:      "abc123def456",
		Name:    "test_web_1",
		Service: "web",
		State:   "running",
		Status:  "Up 5 minutes (healthy)",
		Image:   "nginx:alpine",
		Health:  "healthy",
	}

	if container.Health != "healthy" {
		t.Errorf("Health = %q, expected 'healthy'", container.Health)
	}
}

func TestIsContainerHealthy_WithHealthCheck(t *testing.T) {
	// Mock handler (we only need to test the method logic)
	h := &DeployHandler{}

	tests := []struct {
		name     string
		c        ComposeContainer
		expected bool
	}{
		{
			name:     "healthy with health field",
			c:        ComposeContainer{State: "running", Status: "Up", Health: "healthy"},
			expected: true,
		},
		{
			name:     "unhealthy with health field",
			c:        ComposeContainer{State: "running", Status: "Up", Health: "unhealthy"},
			expected: false,
		},
		{
			name:     "starting with health field",
			c:        ComposeContainer{State: "running", Status: "Up", Health: "starting"},
			expected: false,
		},
		{
			name:     "healthy in status (compose v2 format)",
			c:        ComposeContainer{State: "running", Status: "Up 5 minutes (healthy)"},
			expected: true,
		},
		{
			name:     "unhealthy in status (compose v2 format)",
			c:        ComposeContainer{State: "running", Status: "Up 5 minutes (unhealthy)"},
			expected: false,
		},
		{
			name:     "running no health check",
			c:        ComposeContainer{State: "running", Status: "Up 5 minutes"},
			expected: true,
		},
		{
			name:     "exited no health check",
			c:        ComposeContainer{State: "exited", Status: "Exited (1)"},
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := h.isContainerHealthy(tt.c)
			if result != tt.expected {
				t.Errorf("isContainerHealthy() = %v, expected %v", result, tt.expected)
			}
		})
	}
}

func TestServiceStatus(t *testing.T) {
	// Test ServiceStatus struct
	status := ServiceStatus{
		Name:    "web",
		Status:  "running",
		Image:   "nginx:alpine",
		Message: "Container started",
	}

	if status.Name != "web" {
		t.Errorf("Name = %q, expected 'web'", status.Name)
	}
	if status.Status != "running" {
		t.Errorf("Status = %q, expected 'running'", status.Status)
	}
}

func TestMapContainerStateToServiceStatus(t *testing.T) {
	h := &DeployHandler{}

	tests := []struct {
		name     string
		c        ComposeContainer
		expected string
	}{
		{
			name:     "running container",
			c:        ComposeContainer{State: "running", Status: "Up 5 minutes"},
			expected: "running",
		},
		{
			name:     "running with starting health",
			c:        ComposeContainer{State: "running", Status: "Up", Health: "starting"},
			expected: "starting",
		},
		{
			name:     "created container",
			c:        ComposeContainer{State: "created", Status: "Created"},
			expected: "creating",
		},
		{
			name:     "exited container",
			c:        ComposeContainer{State: "exited", Status: "Exited (1)"},
			expected: "failed",
		},
		{
			name:     "dead container",
			c:        ComposeContainer{State: "dead", Status: "Dead"},
			expected: "failed",
		},
		{
			name:     "restarting container",
			c:        ComposeContainer{State: "restarting", Status: "Restarting"},
			expected: "restarting",
		},
		{
			name:     "healthy container",
			c:        ComposeContainer{State: "running", Status: "Up (healthy)", Health: "healthy"},
			expected: "running",
		},
		{
			name:     "unhealthy container",
			c:        ComposeContainer{State: "running", Status: "Up (unhealthy)", Health: "unhealthy"},
			expected: "unhealthy",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := h.mapContainerStateToServiceStatus(tt.c)
			if result != tt.expected {
				t.Errorf("mapContainerStateToServiceStatus() = %q, expected %q", result, tt.expected)
			}
		})
	}
}
