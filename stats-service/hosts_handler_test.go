package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fakeRegistrar struct {
	added   []string
	removed []string
	err     error
	// onAdd simulates an agent connecting during the registration.
	onAdd func()
}

func (f *fakeRegistrar) AddDockerHost(hostID, hostName, hostAddress, caCert, cert, key string) error {
	if f.err != nil {
		return f.err
	}
	f.added = append(f.added, hostID)
	if f.onAdd != nil {
		f.onAdd()
	}
	return nil
}

func (f *fakeRegistrar) RemoveDockerHost(hostID string) {
	f.removed = append(f.removed, hostID)
}

type fakeSessions struct {
	active map[string]bool
}

func (f *fakeSessions) HasActiveSession(hostID string) bool { return f.active[hostID] }

func postHostsAdd(t *testing.T, h http.HandlerFunc, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/api/hosts/add", strings.NewReader(body))
	w := httptest.NewRecorder()
	h(w, req)
	return w
}

func TestHostsAddHandler_RegistersHostAndMetadata(t *testing.T) {
	reg := &fakeRegistrar{}
	cache := NewStatsCache()
	h := makeHostsAddHandler(reg, cache, &fakeSessions{})

	w := postHostsAdd(t, h, `{"host_id":"host-1","host_name":"h1","host_address":"tcp://1.2.3.4:2376","num_cpus":8,"total_memory":17179869184,"is_local":true}`)
	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
	if len(reg.added) != 1 || reg.added[0] != "host-1" {
		t.Errorf("added=%v, want [host-1]", reg.added)
	}
	if got := cache.GetHostNumCPUs("host-1"); got != 8 {
		t.Errorf("num_cpus=%d, want 8", got)
	}
	if got := cache.GetHostMemory("host-1"); got != 17179869184 {
		t.Errorf("total_memory=%d, want 17179869184", got)
	}
	if !cache.IsHostLocal("host-1") {
		t.Error("is_local not stored")
	}
}

// Disjointness: a host with a live agent ingest session must never also be
// registered as a Docker host, or the aggregator and ingest would both write
// the same host cache key (last-writer-wins).
func TestHostsAddHandler_RejectsHostWithLiveAgentSession(t *testing.T) {
	reg := &fakeRegistrar{}
	cache := NewStatsCache()
	sessions := &fakeSessions{active: map[string]bool{"host-1": true}}
	h := makeHostsAddHandler(reg, cache, sessions)

	w := postHostsAdd(t, h, `{"host_id":"host-1","host_name":"h1","host_address":"tcp://1.2.3.4:2376"}`)
	if w.Code != http.StatusConflict {
		t.Fatalf("status=%d, want 409; body=%s", w.Code, w.Body.String())
	}
	if len(reg.added) != 0 {
		t.Errorf("host was registered despite a live agent session: %v", reg.added)
	}
	if _, ok := cache.GetHostStats("host-1"); ok {
		t.Error("rejected registration still touched the host cache")
	}
}

// A nil session registry (persistence disabled -> no ingest endpoint) must not
// break plain Docker host registration.
func TestHostsAddHandler_NilSessionsRegistryAllowsAdd(t *testing.T) {
	reg := &fakeRegistrar{}
	h := makeHostsAddHandler(reg, NewStatsCache(), nil)

	w := postHostsAdd(t, h, `{"host_id":"host-1","host_name":"h1","host_address":"tcp://1.2.3.4:2376"}`)
	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
}

func TestHostsAddHandler_ValidatesRequiredFields(t *testing.T) {
	h := makeHostsAddHandler(&fakeRegistrar{}, NewStatsCache(), &fakeSessions{})

	for _, body := range []string{
		`{"host_name":"h1","host_address":"tcp://1.2.3.4:2376"}`,
		`{"host_id":"host-1","host_address":"tcp://1.2.3.4:2376"}`,
		`{"host_id":"host-1","host_name":"h1"}`,
	} {
		if w := postHostsAdd(t, h, body); w.Code != http.StatusBadRequest {
			t.Errorf("status=%d for %s, want 400", w.Code, body)
		}
	}
}

func TestHostsAddHandler_RejectsNonPost(t *testing.T) {
	h := makeHostsAddHandler(&fakeRegistrar{}, NewStatsCache(), &fakeSessions{})
	req := httptest.NewRequest(http.MethodGet, "/api/hosts/add", nil)
	w := httptest.NewRecorder()
	h(w, req)
	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("status=%d, want 405", w.Code)
	}
}

func TestHostsAddHandler_RejectsBadJSON(t *testing.T) {
	h := makeHostsAddHandler(&fakeRegistrar{}, NewStatsCache(), &fakeSessions{})
	if w := postHostsAdd(t, h, "{nonsense"); w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400", w.Code)
	}
}

func TestHostsAddHandler_ConflictBodyIsJSON(t *testing.T) {
	sessions := &fakeSessions{active: map[string]bool{"host-1": true}}
	h := makeHostsAddHandler(&fakeRegistrar{}, NewStatsCache(), sessions)

	w := postHostsAdd(t, h, `{"host_id":"host-1","host_name":"h1","host_address":"tcp://1.2.3.4:2376"}`)
	var body map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("conflict body is not JSON: %q", w.Body.String())
	}
	if body["error"] == "" {
		t.Errorf("conflict body missing error field: %v", body)
	}
}

// The two disjointness checks read different registries, so an agent can open
// its session after the pre-check and still find no Docker host to evict. The
// post-registration re-check is what closes that window.
func TestHostsAddHandler_RejectsAgentSessionOpenedDuringRegistration(t *testing.T) {
	sessions := &fakeSessions{active: map[string]bool{}}
	reg := &fakeRegistrar{onAdd: func() { sessions.active["host-1"] = true }}
	h := makeHostsAddHandler(reg, NewStatsCache(), sessions)

	w := postHostsAdd(t, h, `{"host_id":"host-1","host_name":"h1","host_address":"tcp://1.2.3.4:2376"}`)

	if w.Code != http.StatusConflict {
		t.Fatalf("status=%d, want 409; body=%s", w.Code, w.Body.String())
	}
	if len(reg.removed) != 1 || reg.removed[0] != "host-1" {
		t.Errorf("removed=%v, want [host-1]: the racing registration must be rolled back", reg.removed)
	}
}
