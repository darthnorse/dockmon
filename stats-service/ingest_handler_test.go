package main

import (
	"bytes"
	"context"
	"encoding/json"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/dockmon/stats-service/persistence"
	"github.com/gorilla/websocket"
)

func makeIngestFixture(t *testing.T) (*StatsCache, *persistence.DB, *IngestHandler) {
	t.Helper()
	cache := NewStatsCache()
	path := persistence.MakeFixtureDBForTest(t)
	db, err := persistence.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	h := &IngestHandler{
		db:    db,
		cache: cache,
		upgrader: websocket.Upgrader{
			CheckOrigin: func(*http.Request) bool { return true },
		},
	}
	return cache, db, h
}

func TestIngestHandler_RejectsMissingToken(t *testing.T) {
	_, _, h := makeIngestFixture(t)
	srv := httptest.NewServer(http.HandlerFunc(h.HandleWebSocket))
	defer srv.Close()

	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/stats/ingest"
	_, resp, err := websocket.DefaultDialer.Dial(url, nil)
	if err == nil {
		t.Fatal("expected error from missing token")
	}
	if resp == nil || resp.StatusCode != http.StatusUnauthorized {
		t.Errorf("status=%v, want 401", resp)
	}
}

func TestIngestHandler_RejectsInvalidToken(t *testing.T) {
	_, _, h := makeIngestFixture(t)
	srv := httptest.NewServer(http.HandlerFunc(h.HandleWebSocket))
	defer srv.Close()

	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/stats/ingest"
	header := http.Header{"Authorization": {"Bearer unknown-token"}}
	_, resp, err := websocket.DefaultDialer.Dial(url, header)
	if err == nil {
		t.Fatal("expected error for unknown token")
	}
	if resp == nil || resp.StatusCode != http.StatusUnauthorized {
		t.Errorf("status=%v, want 401", resp)
	}
}

func TestIngestHandler_ValidTokenAcceptsStats(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id,name) VALUES ('host-1','h1')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(
		`INSERT INTO agents (id, host_id) VALUES ('valid-tok','host-1')`); err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(h.HandleWebSocket))
	defer srv.Close()

	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/stats/ingest"
	header := http.Header{"Authorization": {"Bearer valid-tok"}}
	conn, _, err := websocket.DefaultDialer.Dial(url, header)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	msg := map[string]interface{}{
		"container_id":   "abc123abc123",
		"container_name": "nginx",
		"cpu_percent":    42.0,
		"memory_usage":   1024,
		"memory_limit":   8192,
		"memory_percent": 12.5,
		"network_rx":     500,
		"network_tx":     500,
	}
	data, _ := json.Marshal(msg)
	if err := conn.WriteMessage(websocket.TextMessage, data); err != nil {
		t.Fatalf("write: %v", err)
	}

	// Poll briefly for the cache update (writer goroutine on server side).
	deadline := time.Now().Add(500 * time.Millisecond)
	var found bool
	for time.Now().Before(deadline) {
		for _, s := range cache.GetAllContainerStats() {
			if s.HostID == "host-1" && s.ContainerID == "abc123abc123" {
				found = true
				if s.CPUPercent != 42.0 {
					t.Errorf("CPU=%v, want 42", s.CPUPercent)
				}
			}
		}
		if found {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !found {
		t.Errorf("expected cache entry for host-1/abc123abc123")
	}
}

func TestIngestHandler_HostIDFromAuthNotMessage(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id,name) VALUES ('host-1','h1'),('host-2','h2')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(
		`INSERT INTO agents (id, host_id) VALUES ('tok1','host-1')`); err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(h.HandleWebSocket))
	defer srv.Close()

	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/stats/ingest"
	header := http.Header{"Authorization": {"Bearer tok1"}}
	conn, _, err := websocket.DefaultDialer.Dial(url, header)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	// Lying agent: claims host_id = host-2 in the message body. The handler's
	// agentStatsMsg struct doesn't deserialize host_id, so this is a no-op,
	// but the test explicitly documents the intent: the client CANNOT
	// influence host_id.
	msg := map[string]interface{}{
		"host_id":      "host-2",
		"container_id": "spoofedabcd1",
		"cpu_percent":  99.0,
		"memory_limit": 1,
	}
	data, _ := json.Marshal(msg)
	if err := conn.WriteMessage(websocket.TextMessage, data); err != nil {
		t.Fatalf("write: %v", err)
	}

	// Give the server goroutine time to process.
	time.Sleep(100 * time.Millisecond)

	for _, s := range cache.GetAllContainerStats() {
		if s.HostID == "host-2" {
			t.Errorf("agent successfully spoofed host_id; got %+v", s)
		}
		if s.ContainerID == "spoofedabcd" && s.HostID != "host-1" {
			t.Errorf("container spoofedabcd bound to wrong host; got %+v", s)
		}
	}
}

func TestIngestHandler_NormalizesLongContainerID(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id,name) VALUES ('host-1','h1')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(
		`INSERT INTO agents (id, host_id) VALUES ('tok1','host-1')`); err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(h.HandleWebSocket))
	defer srv.Close()

	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/stats/ingest"
	header := http.Header{"Authorization": {"Bearer tok1"}}
	conn, _, err := websocket.DefaultDialer.Dial(url, header)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	// 64-char container ID must be normalized to 12.
	longID := strings.Repeat("a", 64)
	msg := map[string]interface{}{
		"container_id": longID,
		"cpu_percent":  1.0,
		"memory_limit": 1,
	}
	data, _ := json.Marshal(msg)
	_ = conn.WriteMessage(websocket.TextMessage, data)

	deadline := time.Now().Add(500 * time.Millisecond)
	for time.Now().Before(deadline) {
		for _, s := range cache.GetAllContainerStats() {
			if s.ContainerID == longID[:12] {
				return // pass
			}
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Errorf("expected normalized 12-char container ID in cache")
}

// TestIngestHandler_ContextCancellationReturnsHandler verifies that when the
// request context is cancelled (e.g. on server shutdown) the handler
// goroutine unblocks from its ReadJSON loop and returns in a timely manner.
// Without the watcher goroutine installed in HandleWebSocket, ReadJSON
// would block until the client disconnected and this test would hang.
func TestIngestHandler_ContextCancellationReturnsHandler(t *testing.T) {
	_, db, h := makeIngestFixture(t)
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id,name) VALUES ('host-1','h1')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(
		`INSERT INTO agents (id, host_id) VALUES ('tok1','host-1')`); err != nil {
		t.Fatal(err)
	}

	// Build a server whose BaseContext we control. Cancelling baseCtx
	// propagates into every r.Context() the server constructs, which is
	// the same signal the real main.go gives its handlers on shutdown.
	baseCtx, cancelBase := context.WithCancel(context.Background())

	// Wrap the handler so the test can observe when it returns.
	var wg sync.WaitGroup
	wrapped := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		wg.Add(1)
		defer wg.Done()
		h.HandleWebSocket(w, r)
	})

	srv := httptest.NewUnstartedServer(wrapped)
	srv.Config.BaseContext = func(net.Listener) context.Context { return baseCtx }
	srv.Start()
	// Defer order matters: cancel the base context BEFORE closing the
	// server so an in-flight handler (blocking on ReadJSON) can unwind
	// via the watcher rather than making srv.Close() hang.
	defer srv.Close()
	defer cancelBase()

	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/stats/ingest"
	header := http.Header{"Authorization": {"Bearer tok1"}}
	conn, _, err := websocket.DefaultDialer.Dial(url, header)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	// Let the handler reach its ReadJSON blocking loop.
	time.Sleep(50 * time.Millisecond)

	// Cancel the server-side base context. The watcher goroutine inside
	// HandleWebSocket should observe this and close the connection,
	// which unblocks ReadJSON and lets the handler return.
	cancelBase()

	done := make(chan struct{})
	go func() {
		wg.Wait()
		close(done)
	}()

	select {
	case <-done:
		// handler returned as expected
	case <-time.After(2 * time.Second):
		t.Fatal("handler did not return within 2s of context cancellation")
	}
}

// dialIngest registers host-1 with token tok1 and returns a connected agent
// WebSocket plus the cache it feeds.
func dialIngest(t *testing.T, h *IngestHandler, db *persistence.DB) *websocket.Conn {
	t.Helper()
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id,name) VALUES ('host-1','h1')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(
		`INSERT INTO agents (id, host_id) VALUES ('tok1','host-1')`); err != nil {
		t.Fatal(err)
	}
	srv := httptest.NewServer(http.HandlerFunc(h.HandleWebSocket))
	t.Cleanup(srv.Close)

	url := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws/stats/ingest"
	conn, _, err := websocket.DefaultDialer.Dial(url,
		http.Header{"Authorization": {"Bearer tok1"}})
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })
	return conn
}

func writeIngestJSON(t *testing.T, conn *websocket.Conn, msg map[string]interface{}) {
	t.Helper()
	data, _ := json.Marshal(msg)
	if err := conn.WriteMessage(websocket.TextMessage, data); err != nil {
		t.Fatalf("write: %v", err)
	}
}

// waitFor polls cond until it holds or the deadline expires.
func waitFor(t *testing.T, cond func() bool) bool {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return true
		}
		time.Sleep(10 * time.Millisecond)
	}
	return false
}

func TestIngestHandler_HostStatsMessageUpdatesHostCache(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	writeIngestJSON(t, conn, map[string]interface{}{
		"type":               "host_stats",
		"cpu_percent":        37.5,
		"memory_percent":     61.25,
		"memory_used_bytes":  8_589_934_592,
		"memory_limit_bytes": 17_179_869_184,
	})

	var stats *HostStats
	if !waitFor(t, func() bool {
		s, ok := cache.GetHostStats("host-1")
		if ok {
			stats = s
		}
		return ok
	}) {
		t.Fatal("host stats never reached the cache")
	}

	if stats.HostID != "host-1" {
		t.Errorf("HostID=%q, want host-1 (must come from auth)", stats.HostID)
	}
	if stats.CPUPercent != 37.5 {
		t.Errorf("CPUPercent=%v, want 37.5", stats.CPUPercent)
	}
	if stats.MemoryPercent != 61.25 {
		t.Errorf("MemoryPercent=%v, want 61.25", stats.MemoryPercent)
	}
	if stats.MemoryUsedBytes != 8_589_934_592 {
		t.Errorf("MemoryUsedBytes=%v, want 8589934592", stats.MemoryUsedBytes)
	}
	if stats.MemoryLimitBytes != 17_179_869_184 {
		t.Errorf("MemoryLimitBytes=%v, want 17179869184", stats.MemoryLimitBytes)
	}
	if stats.LastUpdate.IsZero() {
		t.Error("LastUpdate not stamped; evaluator freshness check would reject the sample")
	}
}

// A host-typed message must never create a container cache entry, even when a
// (bogus) container_id rides along.
func TestIngestHandler_HostStatsDoesNotPolluteContainerCache(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	writeIngestJSON(t, conn, map[string]interface{}{
		"type":           "host_stats",
		"container_id":   "abc123abc123",
		"cpu_percent":    10.0,
		"memory_percent": 20.0,
	})

	if !waitFor(t, func() bool {
		_, ok := cache.GetHostStats("host-1")
		return ok
	}) {
		t.Fatal("host stats never reached the cache")
	}
	if n := len(cache.GetAllContainerStats()); n != 0 {
		t.Errorf("container cache has %d entries, want 0", n)
	}
}

// Agents predating the typed wire format send no `type` field. Those messages
// must keep being treated as container stats.
func TestIngestHandler_UntypedMessageIsContainerStats(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	writeIngestJSON(t, conn, map[string]interface{}{
		"container_id":   "legacy123456",
		"container_name": "old-agent",
		"cpu_percent":    5.0,
	})

	if !waitFor(t, func() bool {
		_, ok := cache.GetContainerStats("legacy123456", "host-1")
		return ok
	}) {
		t.Fatal("legacy untyped message did not land in the container cache")
	}
	if _, ok := cache.GetHostStats("host-1"); ok {
		t.Error("legacy container message polluted the host cache")
	}
}

func TestIngestHandler_ExplicitContainerTypeAccepted(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	writeIngestJSON(t, conn, map[string]interface{}{
		"type":           "container_stats",
		"container_id":   "typed1234567",
		"container_name": "nginx",
		"cpu_percent":    7.5,
	})

	if !waitFor(t, func() bool {
		_, ok := cache.GetContainerStats("typed1234567", "host-1")
		return ok
	}) {
		t.Fatal("explicitly typed container message did not land in the container cache")
	}
}

// An unknown type must be dropped rather than falling through to either cache.
func TestIngestHandler_UnknownTypeDropped(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	writeIngestJSON(t, conn, map[string]interface{}{
		"type":         "something_else",
		"container_id": "unknown12345",
		"cpu_percent":  1.0,
	})
	// Follow with a valid message so we can wait on a deterministic signal.
	writeIngestJSON(t, conn, map[string]interface{}{
		"type":           "host_stats",
		"cpu_percent":    1.0,
		"memory_percent": 1.0,
	})

	if !waitFor(t, func() bool {
		_, ok := cache.GetHostStats("host-1")
		return ok
	}) {
		t.Fatal("host stats never reached the cache")
	}
	if n := len(cache.GetAllContainerStats()); n != 0 {
		t.Errorf("unknown-typed message wrote %d container entries, want 0", n)
	}
}

// The agent/Docker disjointness invariant: while an agent holds an ingest
// session for a host, that host must not also be a registered Docker host.
func TestIngestHandler_TracksActiveAgentSession(t *testing.T) {
	_, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	if !waitFor(t, func() bool { return h.HasActiveSession("host-1") }) {
		t.Fatal("expected an active ingest session for host-1")
	}
	if h.HasActiveSession("host-2") {
		t.Error("host-2 reported as having an ingest session")
	}

	_ = conn.Close()
	if !waitFor(t, func() bool { return !h.HasActiveSession("host-1") }) {
		t.Error("ingest session still active after the agent disconnected")
	}
}

type fakeUnregistrar struct {
	mu      sync.Mutex
	present map[string]bool
	removed []string
}

func (f *fakeUnregistrar) HasHost(hostID string) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.present[hostID]
}

func (f *fakeUnregistrar) RemoveDockerHost(hostID string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.present, hostID)
	f.removed = append(f.removed, hostID)
}

func (f *fakeUnregistrar) removedHosts() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]string(nil), f.removed...)
}

// If a Docker registration for the same host_id survived (stale row, in-place
// connection-type edit), the arriving agent evicts it so the aggregator can
// never overwrite authenticated agent samples.
func TestIngestHandler_EvictsStaleDockerRegistrationOnConnect(t *testing.T) {
	_, db, h := makeIngestFixture(t)
	reg := &fakeUnregistrar{present: map[string]bool{"host-1": true}}
	h.hosts = reg

	dialIngest(t, h, db)

	if !waitFor(t, func() bool { return len(reg.removedHosts()) > 0 }) {
		t.Fatal("stale Docker registration was not evicted on agent connect")
	}
	if got := reg.removedHosts()[0]; got != "host-1" {
		t.Errorf("evicted %q, want host-1", got)
	}
	if reg.HasHost("host-1") {
		t.Error("host still registered as a Docker host after agent takeover")
	}
}

// Same invariant against the real StreamManager rather than a fake.
func TestIngestHandler_AgentTakeoverLeavesNoDockerHost(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	sm := NewStreamManager(cache)
	h.hosts = sm

	if err := sm.AddDockerHost("host-1", "was-docker", "tcp://198.51.100.7:2376", "", "", ""); err != nil {
		t.Fatalf("AddDockerHost: %v", err)
	}
	if !sm.HasHost("host-1") {
		t.Fatal("fixture did not register the Docker host")
	}

	dialIngest(t, h, db)

	if !waitFor(t, func() bool { return !sm.HasHost("host-1") }) {
		t.Error("HasHost still true after an agent claimed the host_id; " +
			"the aggregator would overwrite authenticated agent samples")
	}
}

func TestInvalidateHandler_EvictsCachedToken(t *testing.T) {
	path := persistence.MakeFixtureDBForTest(t)
	db, err := persistence.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id,name) VALUES ('host-1','h1')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(
		`INSERT INTO agents (id, host_id) VALUES ('tok','host-1')`); err != nil {
		t.Fatal(err)
	}

	// Warm the token cache
	if _, err := db.ValidateAgentToken(context.Background(), "tok"); err != nil {
		t.Fatal(err)
	}

	h := &InvalidateHandler{db: db}
	req := httptest.NewRequest(http.MethodPost, "/api/agents/invalidate",
		strings.NewReader(`{"agent_id":"tok"}`))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}

	// Delete the row from the DB; without invalidation the cache would
	// still return the old host_id. With invalidation, the next lookup
	// bypasses the cache and queries the DB → ErrInvalidAgentToken.
	if _, err := db.Write().Exec(`DELETE FROM agents WHERE id = 'tok'`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.ValidateAgentToken(context.Background(), "tok"); err == nil {
		t.Errorf("expected ErrInvalidAgentToken after invalidate")
	}
}

func TestInvalidateHandler_RejectsBadJSON(t *testing.T) {
	path := persistence.MakeFixtureDBForTest(t)
	db, err := persistence.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	h := &InvalidateHandler{db: db}
	req := httptest.NewRequest(http.MethodPost, "/api/agents/invalidate",
		strings.NewReader("{nonsense"))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400", w.Code)
	}
}

func TestInvalidateHandler_RejectsEmptyAgentID(t *testing.T) {
	path := persistence.MakeFixtureDBForTest(t)
	db, err := persistence.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	h := &InvalidateHandler{db: db}
	req := httptest.NewRequest(http.MethodPost, "/api/agents/invalidate",
		strings.NewReader(`{"agent_id":""}`))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400", w.Code)
	}
}

func TestInvalidateHandler_RejectsNonPost(t *testing.T) {
	path := persistence.MakeFixtureDBForTest(t)
	db, err := persistence.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	h := &InvalidateHandler{db: db}
	req := httptest.NewRequest(http.MethodGet, "/api/agents/invalidate", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("status=%d, want 405", w.Code)
	}
}

// msg.Type is agent-controlled up to the 16KB frame limit; an unthrottled log
// line per frame would let one authenticated agent rotate the whole container
// log ring and erase recent history.
func TestIngestHandler_UnknownTypeLoggedOncePerConnection(t *testing.T) {
	cache, db, h := makeIngestFixture(t)

	var logBuf bytes.Buffer
	var logMu sync.Mutex
	log.SetOutput(&syncWriter{mu: &logMu, w: &logBuf})
	t.Cleanup(func() { log.SetOutput(os.Stderr) })

	conn := dialIngest(t, h, db)
	for i := 0; i < 5; i++ {
		writeIngestJSON(t, conn, map[string]interface{}{
			"type":        strings.Repeat("A", 200),
			"cpu_percent": 1.0,
		})
	}
	// Trailing valid message gives us a deterministic signal that all five
	// unknown-typed frames have been processed.
	writeIngestJSON(t, conn, map[string]interface{}{
		"type": "host_stats", "cpu_percent": 1.0, "memory_percent": 1.0,
	})
	if !waitFor(t, func() bool {
		_, ok := cache.GetHostStats("host-1")
		return ok
	}) {
		t.Fatal("host stats never reached the cache")
	}

	logMu.Lock()
	out := logBuf.String()
	logMu.Unlock()

	if n := strings.Count(out, "unknown message type"); n != 1 {
		t.Errorf("logged %d unknown-type lines, want 1", n)
	}
	if strings.Contains(out, strings.Repeat("A", 64)) {
		t.Error("full attacker-controlled type was logged untruncated")
	}
}

type syncWriter struct {
	mu *sync.Mutex
	w  *bytes.Buffer
}

func (s *syncWriter) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.w.Write(p)
}

// --- host disk (Fix D) ---

func hostStatsWithDisk() map[string]interface{} {
	return map[string]interface{}{
		"type":                 "host_stats",
		"cpu_percent":          37.5,
		"memory_percent":       61.25,
		"memory_used_bytes":    8_589_934_592,
		"memory_limit_bytes":   17_179_869_184,
		"disk_percent":         54.7,
		"disk_used_bytes":      53_000_000_000,
		"disk_available_bytes": 44_000_000_000,
		"disk_total_bytes":     103_000_000_000,
		"disk_source":          "/var/lib/docker",
	}
}

func waitForHostStats(t *testing.T, cache *StatsCache, cond func(*HostStats) bool) *HostStats {
	t.Helper()
	var stats *HostStats
	if !waitFor(t, func() bool {
		s, ok := cache.GetHostStats("host-1")
		if ok && cond(s) {
			stats = s
			return true
		}
		return false
	}) {
		t.Fatal("expected host stats never reached the cache")
	}
	return stats
}

func TestIngestHandler_HostStatsCarryDiskIntoCacheAndAPI(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	writeIngestJSON(t, conn, hostStatsWithDisk())

	stats := waitForHostStats(t, cache, func(*HostStats) bool { return true })
	if stats.HostDisk == nil {
		t.Fatal("disk fields did not reach the cache")
	}
	if stats.DiskPercent != 54.7 || stats.DiskUsedBytes != 53_000_000_000 ||
		stats.DiskAvailableBytes != 44_000_000_000 || stats.DiskTotalBytes != 103_000_000_000 ||
		stats.DiskSource != "/var/lib/docker" {
		t.Errorf("disk=%+v, want the message's values", *stats.HostDisk)
	}
	if stats.HostID != "host-1" {
		t.Errorf("HostID=%q, want host-1 from auth", stats.HostID)
	}

	data, err := json.Marshal(cache.GetAllHostStats())
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), `"disk_percent":54.7`) {
		t.Errorf("API payload lost disk_percent: %s", data)
	}
}

// An old agent sends no disk fields; the cache must not hold zeros for it,
// and the API payload must not carry the key.
func TestIngestHandler_HostStatsWithoutDiskLeavesDiskUnsetEndToEnd(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	msg := hostStatsWithDisk()
	for k := range msg {
		if strings.HasPrefix(k, "disk_") {
			delete(msg, k)
		}
	}
	writeIngestJSON(t, conn, msg)

	stats := waitForHostStats(t, cache, func(*HostStats) bool { return true })
	if stats.HostDisk != nil {
		t.Errorf("disk fields fabricated for an old agent: %+v", *stats.HostDisk)
	}

	data, err := json.Marshal(cache.GetAllHostStats())
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "disk_") {
		t.Errorf("API payload carries disk keys for a host that reported none: %s", data)
	}
}

// The five fields are all-or-none: a partial set could be read as a real
// measurement with zeros filled in.
func TestIngestHandler_PartialDiskFieldsAreDropped(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	msg := hostStatsWithDisk()
	delete(msg, "disk_available_bytes")
	writeIngestJSON(t, conn, msg)

	stats := waitForHostStats(t, cache, func(*HostStats) bool { return true })
	if stats.HostDisk != nil {
		t.Errorf("partial disk set accepted: %+v", *stats.HostDisk)
	}
}

func TestIngestHandler_GenuineZeroDiskPercentIsKept(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	msg := hostStatsWithDisk()
	msg["disk_percent"] = 0
	msg["disk_used_bytes"] = 0
	writeIngestJSON(t, conn, msg)

	stats := waitForHostStats(t, cache, func(*HostStats) bool { return true })
	if stats.HostDisk == nil {
		t.Fatal("a genuine 0% reading was dropped")
	}
	data, _ := json.Marshal(stats)
	if !strings.Contains(string(data), `"disk_percent":0`) {
		t.Errorf("0%% did not serialize: %s", data)
	}
}

// A host that stops reporting disk (agent downgrade, unmounted /hostfs, read
// failure) must lose its cached values rather than keep a last-known-good.
func TestIngestHandler_DiskClearedWhenLaterSampleOmitsIt(t *testing.T) {
	cache, db, h := makeIngestFixture(t)
	conn := dialIngest(t, h, db)

	writeIngestJSON(t, conn, hostStatsWithDisk())
	waitForHostStats(t, cache, func(s *HostStats) bool { return s.HostDisk != nil })

	msg := hostStatsWithDisk()
	for k := range msg {
		if strings.HasPrefix(k, "disk_") {
			delete(msg, k)
		}
	}
	msg["cpu_percent"] = 99.0
	writeIngestJSON(t, conn, msg)

	stats := waitForHostStats(t, cache, func(s *HostStats) bool { return s.CPUPercent == 99.0 })
	if stats.HostDisk != nil {
		t.Errorf("stale disk reading merged into the newer sample: %+v", *stats.HostDisk)
	}
}
