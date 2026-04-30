package config

import (
	"os"
	"testing"
)

func TestLoadFromEnv_AgentName_Unset(t *testing.T) {
	t.Setenv("DOCKMON_URL", "wss://example.com")
	t.Setenv("REGISTRATION_TOKEN", "test-token")
	// Capture and restore any ambient AGENT_NAME so this test is hermetic
	// even when t.Cleanup-style restoration isn't provided by os.Unsetenv.
	if prev, ok := os.LookupEnv("AGENT_NAME"); ok {
		t.Cleanup(func() { os.Setenv("AGENT_NAME", prev) })
	} else {
		t.Cleanup(func() { os.Unsetenv("AGENT_NAME") })
	}
	os.Unsetenv("AGENT_NAME")

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
