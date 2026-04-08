package main

import (
	"encoding/json"
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
	var req settingsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad json: "+err.Error(), http.StatusBadRequest)
		return
	}

	h.provider.mu.Lock()
	if req.StatsPersistenceEnabled != nil {
		h.provider.persistEnabled = *req.StatsPersistenceEnabled
	}
	if req.StatsRetentionDays != nil && *req.StatsRetentionDays >= 1 && *req.StatsRetentionDays <= 90 {
		h.provider.retentionDays = *req.StatsRetentionDays
	}
	if req.StatsPointsPerView != nil && *req.StatsPointsPerView >= 100 && *req.StatsPointsPerView <= 2000 {
		h.provider.pointsPerView = *req.StatsPointsPerView
	}
	resp := map[string]any{
		"stats_persistence_enabled": h.provider.persistEnabled,
		"stats_retention_days":      h.provider.retentionDays,
		"stats_points_per_view":     h.provider.pointsPerView,
	}
	h.provider.mu.Unlock()

	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}
