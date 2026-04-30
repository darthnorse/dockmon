package config

import (
	"strings"
	"testing"
)

func TestLoadFromEnv_AgentName_Unset(t *testing.T) {
	t.Setenv("DOCKMON_URL", "wss://example.com")
	t.Setenv("REGISTRATION_TOKEN", "test-token")
	// t.Setenv("AGENT_NAME", "") sets the var to empty for this test and restores
	// any ambient value on cleanup. TrimSpace("") == "" so the assertion below
	// holds for both "unset" and "empty" — they are indistinguishable to LoadFromEnv.
	t.Setenv("AGENT_NAME", "")

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("LoadFromEnv returned error: %v", err)
	}
	if cfg.AgentName != "" {
		t.Errorf("AgentName = %q, want empty string when AGENT_NAME unset", cfg.AgentName)
	}
}

func TestLoadFromEnv_AgentName_Set(t *testing.T) {
	t.Setenv("DOCKMON_URL", "wss://example.com")
	t.Setenv("REGISTRATION_TOKEN", "test-token")
	t.Setenv("AGENT_NAME", "prod-web-01")

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("LoadFromEnv returned error: %v", err)
	}
	if cfg.AgentName != "prod-web-01" {
		t.Errorf("AgentName = %q, want %q", cfg.AgentName, "prod-web-01")
	}
}

func TestLoadFromEnv_AgentName_Whitespace(t *testing.T) {
	t.Setenv("DOCKMON_URL", "wss://example.com")
	t.Setenv("REGISTRATION_TOKEN", "test-token")
	t.Setenv("AGENT_NAME", "  ")

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("LoadFromEnv returned error: %v", err)
	}
	// We trim whitespace so an accidentally-quoted empty value doesn't become a literal blank name.
	if cfg.AgentName != "" {
		t.Errorf("AgentName = %q, want empty string when AGENT_NAME is whitespace-only", cfg.AgentName)
	}
}

func TestLoadFromEnv_AgentName_TooLong(t *testing.T) {
	t.Setenv("DOCKMON_URL", "wss://example.com")
	t.Setenv("REGISTRATION_TOKEN", "test-token")
	t.Setenv("AGENT_NAME", strings.Repeat("a", 256))

	if _, err := LoadFromEnv(); err == nil {
		t.Fatal("expected error for AGENT_NAME exceeding 255 chars, got nil")
	}
}

func TestLoadFromEnv_AgentName_AtLimit(t *testing.T) {
	t.Setenv("DOCKMON_URL", "wss://example.com")
	t.Setenv("REGISTRATION_TOKEN", "test-token")
	name := strings.Repeat("a", 255)
	t.Setenv("AGENT_NAME", name)

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("LoadFromEnv returned error for 255-char AGENT_NAME: %v", err)
	}
	if cfg.AgentName != name {
		t.Errorf("AgentName length = %d, want 255", len(cfg.AgentName))
	}
}

func TestLoadFromEnv_ForceUniqueRegistration_Default(t *testing.T) {
	t.Setenv("DOCKMON_URL", "wss://example.com")
	t.Setenv("REGISTRATION_TOKEN", "test-token")
	t.Setenv("FORCE_UNIQUE_REGISTRATION", "")

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("LoadFromEnv returned error: %v", err)
	}
	if cfg.ForceUniqueRegistration != false {
		t.Errorf("ForceUniqueRegistration = %v, want false when env var unset", cfg.ForceUniqueRegistration)
	}
}

func TestLoadFromEnv_ForceUniqueRegistration_True(t *testing.T) {
	t.Setenv("DOCKMON_URL", "wss://example.com")
	t.Setenv("REGISTRATION_TOKEN", "test-token")
	t.Setenv("FORCE_UNIQUE_REGISTRATION", "true")
	// AGENT_NAME is required when FORCE_UNIQUE_REGISTRATION=true (validated below).
	t.Setenv("AGENT_NAME", "clone-01")

	cfg, err := LoadFromEnv()
	if err != nil {
		t.Fatalf("LoadFromEnv returned error: %v", err)
	}
	if cfg.ForceUniqueRegistration != true {
		t.Errorf("ForceUniqueRegistration = %v, want true", cfg.ForceUniqueRegistration)
	}
}

func TestLoadFromEnv_ForceUniqueRegistration_RequiresAgentName(t *testing.T) {
	t.Setenv("DOCKMON_URL", "wss://example.com")
	t.Setenv("REGISTRATION_TOKEN", "test-token")
	t.Setenv("FORCE_UNIQUE_REGISTRATION", "true")
	// AGENT_NAME deliberately unset — should fail validation at startup.
	t.Setenv("AGENT_NAME", "")

	_, err := LoadFromEnv()
	if err == nil {
		t.Fatal("expected error when FORCE_UNIQUE_REGISTRATION=true without AGENT_NAME, got nil")
	}
	if !strings.Contains(err.Error(), "AGENT_NAME") {
		t.Errorf("error message = %q, want it to mention AGENT_NAME", err.Error())
	}
}
