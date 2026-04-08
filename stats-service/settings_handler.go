package main

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
)

// SettingsHandler accepts partial updates of stats_* settings from Python.
// Python is the only caller — the endpoint is behind authMiddleware (Bearer token).
type SettingsHandler struct {
	provider *mainSettingsProvider
}

type settingsRequest struct {
	StatsPersistenceEnabled *bool `json:"stats_persistence_enabled,omitempty"`
	StatsRetentionDays      *int  `json:"stats_retention_days,omitempty"`
	StatsPointsPerView      *int  `json:"stats_points_per_view,omitempty"`
}

func (h *SettingsHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "POST")
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Decode the payload. An empty body is treated as a no-op "refresh the
	// current snapshot" request — matches Python's Pydantic behaviour when
	// no stats_* keys are in the validated payload — so we only 400 on
	// malformed JSON, not on an empty request body.
	var req settingsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil && !errors.Is(err, io.EOF) {
		http.Error(w, "bad json: "+err.Error(), http.StatusBadRequest)
		return
	}

	persistEnabled, retentionDays, pointsPerView := h.provider.ApplyPartialUpdate(
		req.StatsPersistenceEnabled,
		req.StatsRetentionDays,
		req.StatsPointsPerView,
	)
	resp := map[string]any{
		"stats_persistence_enabled": persistEnabled,
		"stats_retention_days":      retentionDays,
		"stats_points_per_view":     pointsPerView,
	}

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}
