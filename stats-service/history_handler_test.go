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

// TestHistoryHandler_InvalidRange covers the parseHistoryParams whitelist
// — any tier name not in ComputeTiers must return 400 rather than silently
// defaulting.
func TestHistoryHandler_InvalidRange(t *testing.T) {
	_, h := makeHandlerFixture(t)

	req := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123&range=foo", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400 (invalid range)", w.Code)
	}
}

// TestHistoryHandler_InvalidFromTo covers non-numeric from/to values in
// both the range+from/to branch and the auto-tier branch.
func TestHistoryHandler_InvalidFromTo(t *testing.T) {
	_, h := makeHandlerFixture(t)

	cases := []string{
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123&from=abc&to=123",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123&range=1h&from=abc&to=123",
	}
	for _, u := range cases {
		req := httptest.NewRequest("GET", u, nil)
		w := httptest.NewRecorder()
		h.ServeContainer(w, req)
		if w.Code != http.StatusBadRequest {
			t.Errorf("url=%s: status=%d, want 400", u, w.Code)
		}
	}
}

// TestHistoryHandler_FromGreaterThanToInRangeBranch guards the
// range+from/to branch against silently accepting an inverted window. The
// plain from/to branch already rejects this; the range+from/to branch
// used to fall through and return an empty response.
func TestHistoryHandler_FromGreaterThanToInRangeBranch(t *testing.T) {
	_, h := makeHandlerFixture(t)

	req := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123"+
			"&range=1h&from=200&to=100", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400 (from > to)", w.Code)
	}
}

// TestHistoryHandler_Since verifies the incremental-polling path: the
// server shifts the window start to since+1. The response's From reflects
// bucket-boundary truncation, so compare against an unsince'd baseline
// rather than an exact wall-clock value.
func TestHistoryHandler_Since(t *testing.T) {
	_, h := makeHandlerFixture(t)

	baseline := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123"+
			"&from=1000000&to=1000030", nil)
	bw := httptest.NewRecorder()
	h.ServeContainer(bw, baseline)
	if bw.Code != http.StatusOK {
		t.Fatalf("baseline status=%d body=%s", bw.Code, bw.Body.String())
	}
	var base persistence.HistoryResponse
	if err := json.Unmarshal(bw.Body.Bytes(), &base); err != nil {
		t.Fatal(err)
	}

	// since=1_000_014 — the final two fixture rows (1_000_021, 1_000_028)
	// fall strictly past 1_000_014, so the since response should start
	// after the baseline's start and span a strictly narrower grid.
	req := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123"+
			"&from=1000000&to=1000030&since=1000014", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
	var resp persistence.HistoryResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	if resp.From <= base.From {
		t.Errorf("from=%d, baseline.from=%d, want strictly greater (since shifted window)",
			resp.From, base.From)
	}
	if len(resp.Timestamps) >= len(base.Timestamps) {
		t.Errorf("since should produce a narrower grid; got %d vs baseline %d",
			len(resp.Timestamps), len(base.Timestamps))
	}
}

// TestHistoryHandler_ContainerMemPercent checks that the container endpoint
// returns memory_percent computed from memory_usage/memory_limit in the SQL
// layer. Uses a bucket-aligned timestamp (multiple of 36s, which is 5x the
// 7.2s 1h-tier interval) so FillGaps surfaces the row without relying on
// DB-store vs grid-walk alignment coincidences.
func TestHistoryHandler_ContainerMemPercent(t *testing.T) {
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
	// 1_000_008 is a bucket-aligned timestamp for the 1h tier's 7.2s
	// interval: 138890 * 7.2 = 1000008. memory_usage=1024, memory_limit=8192
	// → memory_percent = 12.5.
	if _, err := db.Write().Exec(`INSERT INTO container_stats_history
		(container_id, host_id, timestamp, resolution, cpu_percent, memory_usage, memory_limit)
		VALUES (?,?,?,?,?,?,?)`,
		"h1:abc123abc123", "h1", int64(1_000_008), "1h",
		float64(50), int64(1024), int64(8192)); err != nil {
		t.Fatal(err)
	}
	h := NewHistoryHandler(db, persistence.ComputeTiers(500))

	// Window ≈ 72s spans five 7.2s buckets centered on 1_000_008; the
	// auto-tier path picks the 1h tier (the smallest whose window ≥ 72s).
	req := httptest.NewRequest("GET",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123"+
			"&from=999972&to=1000044", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
	var resp persistence.HistoryResponse
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}

	want := 100.0 * 1024.0 / 8192.0 // 12.5
	var found bool
	var seen []float64
	for _, v := range resp.Mem {
		if v != nil {
			seen = append(seen, *v)
			if *v-want < 0.0001 && *v-want > -0.0001 {
				found = true
			}
		}
	}
	if !found {
		t.Errorf("expected a mem sample ≈ %v (1024/8192*100); non-nil mem samples=%v",
			want, seen)
	}
}

// TestHistoryHandler_RejectsNonGet ensures the handler enforces method
// restriction. Defense in depth at the handler avoids accidental POST
// processing if the mux changes.
func TestHistoryHandler_RejectsNonGet(t *testing.T) {
	_, h := makeHandlerFixture(t)

	req := httptest.NewRequest("POST",
		"/api/stats/history/container?host_id=h1&container_id=h1:abc123abc123&range=1h", nil)
	w := httptest.NewRecorder()
	h.ServeContainer(w, req)

	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("status=%d, want 405", w.Code)
	}
	if allow := w.Header().Get("Allow"); allow != "GET" {
		t.Errorf("Allow=%q, want GET", allow)
	}
}
