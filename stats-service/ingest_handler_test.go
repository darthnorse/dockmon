package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
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
