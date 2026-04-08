package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestSettingsHandler_UpdatesProvider(t *testing.T) {
	provider := &mainSettingsProvider{retentionDays: 30, pointsPerView: 500, persistEnabled: true}
	h := &SettingsHandler{provider: provider}

	body := `{"stats_persistence_enabled":false,"stats_retention_days":7,"stats_points_per_view":250}`
	req := httptest.NewRequest(http.MethodPost, "/api/settings", bytes.NewBufferString(body))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
	}
	if provider.RetentionDays() != 7 {
		t.Errorf("retention_days=%d, want 7", provider.RetentionDays())
	}
	if provider.PointsPerView() != 250 {
		t.Errorf("points_per_view=%d, want 250", provider.PointsPerView())
	}
	if provider.PersistEnabled() != false {
		t.Errorf("persist_enabled=%v, want false", provider.PersistEnabled())
	}
}

func TestSettingsHandler_ReturnsBadJSON(t *testing.T) {
	provider := &mainSettingsProvider{}
	h := &SettingsHandler{provider: provider}
	req := httptest.NewRequest(http.MethodPost, "/api/settings", bytes.NewBufferString("{nonsense"))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusBadRequest {
		t.Errorf("status=%d, want 400", w.Code)
	}
}

func TestSettingsHandler_AcceptsPartialUpdate(t *testing.T) {
	provider := &mainSettingsProvider{retentionDays: 30, pointsPerView: 500, persistEnabled: true}
	h := &SettingsHandler{provider: provider}
	req := httptest.NewRequest(http.MethodPost, "/api/settings",
		bytes.NewBufferString(`{"stats_retention_days":15}`))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status=%d", w.Code)
	}
	if provider.RetentionDays() != 15 {
		t.Errorf("retention_days=%d, want 15", provider.RetentionDays())
	}
	if provider.PointsPerView() != 500 {
		t.Errorf("points_per_view=%d, want 500 (preserved)", provider.PointsPerView())
	}

	var resp map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	if resp["stats_retention_days"].(float64) != 15 {
		t.Errorf("resp retention_days=%v, want 15", resp["stats_retention_days"])
	}
}

func TestSettingsHandler_RejectsOutOfRange(t *testing.T) {
	provider := &mainSettingsProvider{retentionDays: 30, pointsPerView: 500, persistEnabled: true}
	h := &SettingsHandler{provider: provider}
	// retention_days=1000 is above the 90 ceiling
	req := httptest.NewRequest(http.MethodPost, "/api/settings",
		bytes.NewBufferString(`{"stats_retention_days":1000}`))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("status=%d (handler returns 200 but silently rejects)", w.Code)
	}
	// Out-of-range value is silently ignored (safest for a POST hot-reload)
	if provider.RetentionDays() != 30 {
		t.Errorf("retention_days=%d, want 30 (unchanged)", provider.RetentionDays())
	}
}

func TestSettingsHandler_RejectsNonPost(t *testing.T) {
	h := &SettingsHandler{provider: &mainSettingsProvider{}}
	req := httptest.NewRequest(http.MethodGet, "/api/settings", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != http.StatusMethodNotAllowed {
		t.Errorf("status=%d, want 405", w.Code)
	}
}

// An empty body (Content-Length: 0) should be treated as a no-op read of the
// current snapshot, not a 400. Python never sends an empty body (the client
// short-circuits when the payload map is empty), but we keep this behaviour
// as defence-in-depth so an unauthenticated ping from the same token doesn't
// turn into a 4xx avalanche in the stats-service logs.
func TestSettingsHandler_EmptyBodyIsNoop(t *testing.T) {
	provider := &mainSettingsProvider{retentionDays: 30, pointsPerView: 500, persistEnabled: true}
	h := &SettingsHandler{provider: provider}
	req := httptest.NewRequest(http.MethodPost, "/api/settings", bytes.NewBufferString(""))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status=%d, want 200 (empty body should be a no-op)", w.Code)
	}
	if provider.RetentionDays() != 30 {
		t.Errorf("retention_days=%d, want 30 (unchanged)", provider.RetentionDays())
	}
	if provider.PointsPerView() != 500 {
		t.Errorf("points_per_view=%d, want 500 (unchanged)", provider.PointsPerView())
	}
	if !provider.PersistEnabled() {
		t.Errorf("persist_enabled=false, want true (unchanged)")
	}

	var resp map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("response should echo current snapshot: %v", err)
	}
	if resp["stats_retention_days"].(float64) != 30 {
		t.Errorf("resp retention_days=%v, want 30", resp["stats_retention_days"])
	}
}

// Same for {} — Python sends this if it ever needs to probe the current
// config without changing anything.
func TestSettingsHandler_EmptyObjectIsNoop(t *testing.T) {
	provider := &mainSettingsProvider{retentionDays: 42, pointsPerView: 800, persistEnabled: true}
	h := &SettingsHandler{provider: provider}
	req := httptest.NewRequest(http.MethodPost, "/api/settings", bytes.NewBufferString("{}"))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status=%d, want 200", w.Code)
	}
	if provider.RetentionDays() != 42 {
		t.Errorf("retention_days changed to %d, want 42 (unchanged)", provider.RetentionDays())
	}
}
