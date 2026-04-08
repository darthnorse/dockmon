package main

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
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
