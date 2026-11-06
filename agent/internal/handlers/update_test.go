package handlers

import (
	"encoding/json"
	"errors"
	"io"
	"reflect"
	"testing"

	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/darthnorse/dockmon-shared/update"
	"github.com/sirupsen/logrus"
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

type recordedEvent struct {
	msgType string
	payload map[string]interface{}
}

func recordingHandler() (*UpdateHandler, *[]recordedEvent) {
	events := &[]recordedEvent{}
	log := logrus.New()
	log.SetOutput(io.Discard)
	return &UpdateHandler{
		log: log,
		sendEvent: func(msgType string, payload interface{}) error {
			*events = append(*events, recordedEvent{msgType, payload.(map[string]interface{})})
			return nil
		},
	}, events
}

func TestReportFailureWithRequestID(t *testing.T) {
	handler, events := recordingHandler()

	handler.reportFailure("16678699c1634a4c", "req-1", &update.UpdateResult{
		Error:            "health check failed",
		RolledBack:       true,
		FailedDependents: []string{"qbittorrent"},
	})

	if len(*events) != 2 {
		t.Fatalf("expected progress and update_failed, got %+v", *events)
	}
	progress, failed := (*events)[0], (*events)[1]
	if progress.msgType != "update_progress" || progress.payload["stage"] != update.StageRollback || progress.payload["request_id"] != "req-1" {
		t.Errorf("unexpected progress event: %+v", progress)
	}
	if failed.msgType != "update_failed" {
		t.Fatalf("expected update_failed, got %s", failed.msgType)
	}
	want := map[string]interface{}{
		"request_id":        "req-1",
		"container_id":      "16678699c163",
		"error":             "health check failed",
		"rolled_back":       true,
		"failed_dependents": []string{"qbittorrent"},
	}
	if !reflect.DeepEqual(failed.payload, want) {
		t.Errorf("update_failed payload = %+v, want %+v", failed.payload, want)
	}
}

func TestReportFailureWithoutRequestIDSendsOnlyProgress(t *testing.T) {
	handler, events := recordingHandler()

	handler.reportFailure("16678699c163", "", &update.UpdateResult{Error: "pull failed"})

	if len(*events) != 1 || (*events)[0].msgType != "update_progress" {
		t.Fatalf("an older backend must only get progress, got %+v", *events)
	}
	want := map[string]interface{}{
		"container_id": "16678699c163",
		"stage":        update.StageFailed,
		"message":      "pull failed",
	}
	if !reflect.DeepEqual((*events)[0].payload, want) {
		t.Errorf("progress payload = %+v, want %+v", (*events)[0].payload, want)
	}
}

func TestReportFailureStillSendsUpdateFailedWhenProgressSendFails(t *testing.T) {
	handler, _ := recordingHandler()
	var sent []string
	handler.sendEvent = func(msgType string, payload interface{}) error {
		sent = append(sent, msgType)
		if msgType == "update_progress" {
			return errors.New("write failed")
		}
		return nil
	}

	handler.reportFailure("16678699c163", "req-1", &update.UpdateResult{Error: "boom"})

	if !reflect.DeepEqual(sent, []string{"update_progress", "update_failed"}) {
		t.Errorf("sent = %v", sent)
	}
}

func TestCompletionPayloadRequestID(t *testing.T) {
	result := &update.UpdateResult{OldContainerID: "old", NewContainerID: "new", ContainerName: "gluetun"}

	if got := completionPayload("req-1", result); got["request_id"] != "req-1" {
		t.Errorf("expected the request ID, got %+v", got)
	}
	if _, present := completionPayload("", result)["request_id"]; present {
		t.Error("an older backend's payload must not change")
	}
}
