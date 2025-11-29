package handlers

import (
	"encoding/json"
	"testing"

	"github.com/darthnorse/dockmon-agent/internal/docker"
)

func TestUpdateRequestUnmarshal(t *testing.T) {
	// Test basic request without registry auth
	jsonData := `{
		"container_id": "abc123def456",
		"new_image": "nginx:1.25",
		"stop_timeout": 30,
		"health_timeout": 120
	}`

	var req UpdateRequest
	if err := json.Unmarshal([]byte(jsonData), &req); err != nil {
		t.Fatalf("failed to unmarshal JSON: %v", err)
	}

	if req.ContainerID != "abc123def456" {
		t.Errorf("expected container_id 'abc123def456', got %q", req.ContainerID)
	}

	if req.NewImage != "nginx:1.25" {
		t.Errorf("expected new_image 'nginx:1.25', got %q", req.NewImage)
	}

	if req.StopTimeout != 30 {
		t.Errorf("expected stop_timeout 30, got %d", req.StopTimeout)
	}

	if req.HealthTimeout != 120 {
		t.Errorf("expected health_timeout 120, got %d", req.HealthTimeout)
	}

	if req.RegistryAuth != nil {
		t.Errorf("expected registry_auth nil, got %+v", req.RegistryAuth)
	}
}

func TestUpdateRequestWithRegistryAuth(t *testing.T) {
	// Test request with registry auth
	jsonData := `{
		"container_id": "abc123def456",
		"new_image": "ghcr.io/myorg/myapp:v2",
		"registry_auth": {
			"username": "myuser",
			"password": "mypassword"
		}
	}`

	var req UpdateRequest
	if err := json.Unmarshal([]byte(jsonData), &req); err != nil {
		t.Fatalf("failed to unmarshal JSON: %v", err)
	}

	if req.RegistryAuth == nil {
		t.Fatal("expected registry_auth not nil")
	}

	if req.RegistryAuth.Username != "myuser" {
		t.Errorf("expected username 'myuser', got %q", req.RegistryAuth.Username)
	}

	if req.RegistryAuth.Password != "mypassword" {
		t.Errorf("expected password 'mypassword', got %q", req.RegistryAuth.Password)
	}
}

func TestUpdateRequestWithNullRegistryAuth(t *testing.T) {
	// Test request with explicit null registry auth
	jsonData := `{
		"container_id": "abc123def456",
		"new_image": "nginx:latest",
		"registry_auth": null
	}`

	var req UpdateRequest
	if err := json.Unmarshal([]byte(jsonData), &req); err != nil {
		t.Fatalf("failed to unmarshal JSON: %v", err)
	}

	if req.RegistryAuth != nil {
		t.Errorf("expected registry_auth nil, got %+v", req.RegistryAuth)
	}
}

func TestRegistryAuthConversionToDockerType(t *testing.T) {
	// Test conversion from handlers.RegistryAuth to docker.RegistryAuth
	handlerAuth := &RegistryAuth{
		Username: "testuser",
		Password: "testpass",
	}

	// This mimics the conversion in UpdateContainer method
	var dockerAuth *docker.RegistryAuth
	if handlerAuth != nil {
		dockerAuth = &docker.RegistryAuth{
			Username: handlerAuth.Username,
			Password: handlerAuth.Password,
		}
	}

	if dockerAuth == nil {
		t.Fatal("expected dockerAuth not nil")
	}

	if dockerAuth.Username != "testuser" {
		t.Errorf("expected username 'testuser', got %q", dockerAuth.Username)
	}

	if dockerAuth.Password != "testpass" {
		t.Errorf("expected password 'testpass', got %q", dockerAuth.Password)
	}
}

func TestRegistryAuthConversionNil(t *testing.T) {
	// Test conversion when handlers.RegistryAuth is nil
	var handlerAuth *RegistryAuth

	// This mimics the conversion in UpdateContainer method
	var dockerAuth *docker.RegistryAuth
	if handlerAuth != nil {
		dockerAuth = &docker.RegistryAuth{
			Username: handlerAuth.Username,
			Password: handlerAuth.Password,
		}
	}

	if dockerAuth != nil {
		t.Errorf("expected dockerAuth nil, got %+v", dockerAuth)
	}
}

func TestUpdateRequestDefaults(t *testing.T) {
	// Test that defaults are not applied during unmarshal (they're applied at runtime)
	jsonData := `{
		"container_id": "abc123def456",
		"new_image": "nginx:latest"
	}`

	var req UpdateRequest
	if err := json.Unmarshal([]byte(jsonData), &req); err != nil {
		t.Fatalf("failed to unmarshal JSON: %v", err)
	}

	// Unmarshal should leave these as zero values
	if req.StopTimeout != 0 {
		t.Errorf("expected stop_timeout 0 from unmarshal, got %d", req.StopTimeout)
	}

	if req.HealthTimeout != 0 {
		t.Errorf("expected health_timeout 0 from unmarshal, got %d", req.HealthTimeout)
	}
}
