package docker

import (
	"encoding/base64"
	"encoding/json"
	"sync"
	"testing"

	"github.com/docker/docker/api/types/registry"
)

// newCacheClient returns a Client with just the fields needed to exercise the
// startedAt cache — no Docker socket, no logger. The other fields stay zero.
func newCacheClient() *Client {
	return &Client{startedAt: make(map[string]string)}
}

func TestStartedAtCache_RecordLookupEvict(t *testing.T) {
	c := newCacheClient()

	if got, ok := c.LookupStartedAt("abc"); ok || got != "" {
		t.Fatalf("empty lookup: got (%q, %v), want (\"\", false)", got, ok)
	}

	c.RecordStartedAt("abc", "2026-04-29T10:00:00Z")
	if got, ok := c.LookupStartedAt("abc"); !ok || got != "2026-04-29T10:00:00Z" {
		t.Fatalf("after record: got (%q, %v), want (\"2026-04-29T10:00:00Z\", true)", got, ok)
	}

	c.EvictContainerCache("abc")
	if _, ok := c.LookupStartedAt("abc"); ok {
		t.Fatalf("after evict: entry still present")
	}

	// Evicting a non-existent key is a no-op.
	c.EvictContainerCache("never-there")
}

func TestStartedAtCache_RejectsEmptyKeys(t *testing.T) {
	c := newCacheClient()

	c.RecordStartedAt("", "2026-04-29T10:00:00Z") // empty id
	c.RecordStartedAt("abc", "")                  // empty timestamp

	if len(c.startedAt) != 0 {
		t.Fatalf("guard failed: cache has %d entries, want 0", len(c.startedAt))
	}
}

func TestStartedAtCache_OverwritesExistingEntry(t *testing.T) {
	c := newCacheClient()

	c.RecordStartedAt("abc", "first")
	c.RecordStartedAt("abc", "second")

	got, _ := c.LookupStartedAt("abc")
	if got != "second" {
		t.Fatalf("overwrite: got %q, want %q", got, "second")
	}
}

func TestStartedAtCache_Reset(t *testing.T) {
	c := newCacheClient()

	c.RecordStartedAt("a", "t1")
	c.RecordStartedAt("b", "t2")
	c.RecordStartedAt("c", "t3")

	c.ResetStartedAtCache()

	if len(c.startedAt) != 0 {
		t.Fatalf("reset: cache has %d entries, want 0", len(c.startedAt))
	}
	c.RecordStartedAt("a", "t4")
	if got, _ := c.LookupStartedAt("a"); got != "t4" {
		t.Fatalf("post-reset record/lookup: got %q, want %q", got, "t4")
	}
}

func TestStartedAtCache_ConcurrentReadWrite(t *testing.T) {
	// Smoke test for the RWMutex: parallel readers and writers should
	// not race under -race.
	c := newCacheClient()

	var wg sync.WaitGroup
	const writers = 8
	const readers = 16
	const opsPerWorker = 200

	for w := 0; w < writers; w++ {
		w := w
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < opsPerWorker; i++ {
				id := string(rune('a'+w)) + string(rune('0'+i%10))
				if i%5 == 0 {
					c.EvictContainerCache(id)
				} else {
					c.RecordStartedAt(id, "ts")
				}
			}
		}()
	}
	for r := 0; r < readers; r++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < opsPerWorker; i++ {
				_, _ = c.LookupStartedAt("a0")
			}
		}()
	}
	wg.Wait()
}

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
