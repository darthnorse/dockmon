package docker

import (
	"encoding/base64"
	"encoding/json"
	"testing"

	"github.com/docker/docker/api/types/registry"
)

func TestEncodeRegistryAuth(t *testing.T) {
	tests := []struct {
		name     string
		auth     *RegistryAuth
		wantEmpty bool
	}{
		{
			name:      "nil auth returns empty",
			auth:      nil,
			wantEmpty: true,
		},
		{
			name:      "empty username returns empty",
			auth:      &RegistryAuth{Username: "", Password: "secret"},
			wantEmpty: true,
		},
		{
			name:      "valid credentials return encoded string",
			auth:      &RegistryAuth{Username: "testuser", Password: "testpass"},
			wantEmpty: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := encodeRegistryAuth(tt.auth)

			if tt.wantEmpty && result != "" {
				t.Errorf("expected empty string, got %q", result)
			}

			if !tt.wantEmpty && result == "" {
				t.Errorf("expected non-empty string, got empty")
			}
		})
	}
}

func TestEncodeRegistryAuthFormat(t *testing.T) {
	auth := &RegistryAuth{
		Username: "myuser",
		Password: "mypassword",
	}

	encoded := encodeRegistryAuth(auth)

	// Decode and verify the format
	decoded, err := base64.URLEncoding.DecodeString(encoded)
	if err != nil {
		t.Fatalf("failed to decode base64: %v", err)
	}

	var authConfig registry.AuthConfig
	if err := json.Unmarshal(decoded, &authConfig); err != nil {
		t.Fatalf("failed to unmarshal JSON: %v", err)
	}

	if authConfig.Username != "myuser" {
		t.Errorf("expected username 'myuser', got %q", authConfig.Username)
	}

	if authConfig.Password != "mypassword" {
		t.Errorf("expected password 'mypassword', got %q", authConfig.Password)
	}
}

func TestRegistryAuthStruct(t *testing.T) {
	// Test JSON unmarshaling
	jsonData := `{"username": "testuser", "password": "testpass"}`

	var auth RegistryAuth
	if err := json.Unmarshal([]byte(jsonData), &auth); err != nil {
		t.Fatalf("failed to unmarshal JSON: %v", err)
	}

	if auth.Username != "testuser" {
		t.Errorf("expected username 'testuser', got %q", auth.Username)
	}

	if auth.Password != "testpass" {
		t.Errorf("expected password 'testpass', got %q", auth.Password)
	}
}

func TestRegistryAuthStructOptionalFields(t *testing.T) {
	// Test JSON unmarshaling with missing fields
	jsonData := `{}`

	var auth RegistryAuth
	if err := json.Unmarshal([]byte(jsonData), &auth); err != nil {
		t.Fatalf("failed to unmarshal JSON: %v", err)
	}

	if auth.Username != "" {
		t.Errorf("expected empty username, got %q", auth.Username)
	}

	if auth.Password != "" {
		t.Errorf("expected empty password, got %q", auth.Password)
	}
}
