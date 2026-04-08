package main

import (
	"encoding/json"
	"net/http"

	"github.com/dockmon/stats-service/persistence"
)

// InvalidateHandler evicts an agent's cached token entry from stats-service.
// Python's agent-deletion flow posts here after the agent row is dropped, so
// the next reconnect attempt from a deleted agent fails fast instead of
// waiting up to 5 minutes for the cache TTL. See spec §10.
type InvalidateHandler struct {
	db *persistence.DB
}

type invalidateRequest struct {
	AgentID string `json:"agent_id"`
}

func (h *InvalidateHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", "POST")
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var req invalidateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad json: "+err.Error(), http.StatusBadRequest)
		return
	}
	if req.AgentID == "" {
		http.Error(w, "agent_id required", http.StatusBadRequest)
		return
	}
	h.db.InvalidateAgentToken(req.AgentID)
	w.WriteHeader(http.StatusOK)
}
