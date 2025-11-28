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
