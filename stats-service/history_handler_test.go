package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/dockmon/stats-service/persistence"
)

func makeHandlerFixture(t *testing.T) (*persistence.DB, *HistoryHandler) {
	t.Helper()
	path := persistence.MakeFixtureDBForTest(t)
	db, err := persistence.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id,name) VALUES ('h1','h1')`); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		if _, err := db.Write().Exec(`INSERT INTO container_stats_history
			(container_id, host_id, timestamp, resolution, cpu_percent, memory_usage, memory_limit)
			VALUES (?,?,?,?,?,?,?)`,
			"h1:abc123abc123", "h1", int64(1_000_000+i*7), "1h",
			float64(i*10), int64(i*100), int64(8192)); err != nil {
			t.Fatal(err)
		}
	}
	return db, NewHistoryHandler(db, persistence.ComputeTiers(500))
}

func TestHistoryHandler_RangeOnly(t *testing.T) {
	_, h := makeHandlerFixture(t)

	req := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123&range=1h", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
	var resp persistence.HistoryResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	if resp.Tier != "1h" {
		t.Errorf("tier=%q, want 1h", resp.Tier)
	}
	if len(resp.Timestamps) == 0 {
		t.Errorf("expected non-empty timestamps")
	}
}

func TestHistoryHandler_FromToWithoutRange(t *testing.T) {
	_, h := makeHandlerFixture(t)

	req := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123"+
			"&from=1000000&to=1000028", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
}

func TestHistoryHandler_MissingRangeAndFromReturns400(t *testing.T) {
	_, h := makeHandlerFixture(t)

	req := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400", w.Code)
	}
}

func TestHistoryHandler_RangeWindowTooBigForTier(t *testing.T) {
	_, h := makeHandlerFixture(t)

	// range=1h with from/to spanning >1h should reject
	req := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123"+
			"&range=1h&from=1000000&to=1007200", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400 (window > tier)", w.Code)
	}
}

func TestHistoryHandler_HostEndpoint(t *testing.T) {
	db, h := makeHandlerFixture(t)
	if _, err := db.Write().Exec(`INSERT INTO host_stats_history
		(host_id, timestamp, resolution, cpu_percent, memory_percent)
		VALUES ('h1', 1000000, '1h', 50.0, 60.0)`); err != nil {
		t.Fatal(err)
	}

	req := httptest.NewRequest("GET",
		"/api/stats/history/host?host_id=h1&range=1h", nil)
	w := httptest.NewRecorder()
	h.ServeHost(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
}

func TestHistoryHandler_MissingContainerID(t *testing.T) {
	_, h := makeHandlerFixture(t)

	req := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&range=1h", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400 (missing container_id)", w.Code)
	}
}

func TestHistoryHandler_MissingHostID(t *testing.T) {
	_, h := makeHandlerFixture(t)

	req := httptest.NewRequest("GET",
		"/api/stats/history/host?range=1h", nil)
	w := httptest.NewRecorder()
	h.ServeHost(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400 (missing host_id)", w.Code)
	}
}
