package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/dockmon/stats-service/persistence"
	"github.com/gorilla/websocket"
)

// TestIntegration_AgentToHistoryRoundTrip wires the full persistence stack
// in-process and verifies an agent-sent stats event becomes a history row
// that the read endpoint returns. This is the primary end-to-end smoke test
// for the feature.
//
// Timing: tier 0's interval at points_per_view=500 is 7.2 seconds. We push
// samples at 200ms cadence for ~10 seconds so the cascade emits at least
// one tier-0 bucket via the 1-second writer tick.
func TestIntegration_AgentToHistoryRoundTrip(t *testing.T) {
	if testing.Short() {
		t.Skip("integration test (takes ~12s); use -short to skip")
	}

	cache := NewStatsCache()
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
		`INSERT INTO agents (id, host_id) VALUES ('integration-tok','host-1')`); err != nil {
		t.Fatal(err)
	}

	tiers := persistence.ComputeTiers(500)
	writes := make(chan persistence.WriteJob, 256)
	cascade := persistence.NewCascade(tiers, writes)
	writer := persistence.NewWriter(db, writes)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go writer.Run(ctx)

	// Fake aggregator: pushes cache contents into the cascade every 100ms
	// (instead of the production 1s tick) so the 10-second test window
	// produces enough tier-0 ingest calls to cross a 7.2s bucket boundary.
	go func() {
		ticker := time.NewTicker(100 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case now := <-ticker.C:
				for _, cs := range cache.GetAllContainerStats() {
					compositeID := cs.HostID + ":" + cs.ContainerID
					cascade.Ingest(compositeID, false, now, persistence.Sample{
						CPU:        cs.CPUPercent,
						MemPercent: cs.MemoryPercent,
						MemUsed:    cs.MemoryUsage,
						MemLimit:   cs.MemoryLimit,
						NetBps:     cs.NetBytesPerSec,
					})
				}
			}
		}
	}()

	mux := http.NewServeMux()
	ingest := &IngestHandler{
		db:    db,
		cache: cache,
		upgrader: websocket.Upgrader{
			CheckOrigin: func(*http.Request) bool { return true },
		},
	}
	history := NewHistoryHandler(db, tiers)
	mux.HandleFunc("/api/stats/ws/ingest", ingest.HandleWebSocket)
	mux.HandleFunc("/api/stats/history/container", history.ServeContainer)

	srv := httptest.NewServer(mux)
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http") + "/api/stats/ws/ingest"
	header := http.Header{"Authorization": {"Bearer integration-tok"}}
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, header)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	// Push 50 samples at 200ms cadence → ~10 seconds of wall clock, enough
	// to cross a tier-0 (7.2s) bucket boundary at least once.
	for i := 0; i < 50; i++ {
		msg := map[string]interface{}{
			"container_id":   "abc123abc123",
			"container_name": "nginx",
			"cpu_percent":    float64(10 + i),
			"memory_usage":   1024 + i*10,
			"memory_limit":   8192,
			"memory_percent": float64(12 + i),
			"network_rx":     500,
			"network_tx":     500,
		}
		if err := conn.WriteJSON(msg); err != nil {
			t.Fatalf("write: %v", err)
		}
		time.Sleep(200 * time.Millisecond)
	}

	// Give the cascade one more aggregator tick + the writer's 1-second
	// flush tick to commit any in-flight bucket.
	time.Sleep(2 * time.Second)

	// Query the history endpoint via a direct HTTP GET (as a Python proxy
	// would in production).
	resp, err := http.Get(srv.URL +
		"/api/stats/history/container?host_id=host-1&container_id=host-1:abc123abc123&range=1h")
	if err != nil {
		t.Fatalf("history GET: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		body, _ := io.ReadAll(resp.Body)
		t.Fatalf("history status=%d body=%s", resp.StatusCode, string(body))
	}

	var body persistence.HistoryResponse
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body.Tier != "1h" {
		t.Errorf("tier=%q, want 1h", body.Tier)
	}

	nonNullCPU := 0
	for _, v := range body.CPU {
		if v != nil {
			nonNullCPU++
		}
	}
	if nonNullCPU == 0 {
		t.Errorf("expected at least one non-null CPU bucket; got all nulls in %d-slot timeline",
			len(body.CPU))
	}

	// Memory percent should also be populated (Task 13 added SQL-computed memory_percent
	// for container queries).
	nonNullMem := 0
	for _, v := range body.Mem {
		if v != nil {
			nonNullMem++
		}
	}
	if nonNullMem == 0 {
		t.Errorf("expected at least one non-null Mem bucket; got all nulls")
	}

	t.Logf("Integration test passed: %d CPU buckets, %d Mem buckets, tier=%s",
		nonNullCPU, nonNullMem, body.Tier)
}
