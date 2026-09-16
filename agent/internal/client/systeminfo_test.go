package client

import (
	"encoding/json"
	"testing"

	"github.com/darthnorse/dockmon-agent/internal/docker"
)

// The nightly get_system_info response and the registration message must
// carry the same keys, or the backend's host row refresh reads nothing.
func TestSystemInfoPayload_MatchesRegistrationKeys(t *testing.T) {
	info := &docker.SystemInfo{
		Hostname: "mediadmz", OSType: "linux", OSVersion: "Debian GNU/Linux 13 (trixie)",
		KernelVersion: "6.12.48", DockerVersion: "29.0.0", DaemonStartedAt: "2026-09-16T02:00:00Z",
		TotalMemory: 16_000_000_000, NumCPUs: 8,
	}

	payload := systemInfoPayload(info)

	want := map[string]interface{}{
		"os_type":           "linux",
		"os_version":        "Debian GNU/Linux 13 (trixie)",
		"kernel_version":    "6.12.48",
		"docker_version":    "29.0.0",
		"daemon_started_at": "2026-09-16T02:00:00Z",
		"total_memory":      int64(16_000_000_000),
		"num_cpus":          8,
	}
	if len(payload) != len(want) {
		t.Fatalf("payload has %d keys, want %d: %v", len(payload), len(want), payload)
	}
	for k, v := range want {
		if payload[k] != v {
			t.Errorf("%s=%v (%T), want %v (%T)", k, payload[k], payload[k], v, v)
		}
	}
	if _, err := json.Marshal(payload); err != nil {
		t.Fatal(err)
	}
}
