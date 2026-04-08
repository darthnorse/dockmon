package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"time"

	"github.com/dockmon/stats-service/persistence"
)

// HistoryHandler serves GET /api/stats/history/{container,host}.
type HistoryHandler struct {
	db    *persistence.DB
	tiers []persistence.Tier
}

// NewHistoryHandler builds a HistoryHandler.
func NewHistoryHandler(db *persistence.DB, tiers []persistence.Tier) *HistoryHandler {
	return &HistoryHandler{db: db, tiers: tiers}
}

type historyParams struct {
	tier     persistence.Tier
	from     time.Time
	to       time.Time
	since    int64
	hasSince bool
}

// parseHistoryParams maps the query string to a normalized (tier, window) pair.
// Spec §9 'Query parameter semantics'.
func parseHistoryParams(q map[string][]string, tiers []persistence.Tier) (historyParams, error) {
	get := func(k string) string {
		if v, ok := q[k]; ok && len(v) > 0 {
			return v[0]
		}
		return ""
	}

	rangeStr := get("range")
	fromStr := get("from")
	toStr := get("to")
	sinceStr := get("since")

	if rangeStr == "" && fromStr == "" {
		return historyParams{}, errors.New("must specify range or from/to")
	}

	now := time.Now()
	var p historyParams

	if rangeStr != "" {
		t, ok := tierByName(tiers, rangeStr)
		if !ok {
			return historyParams{}, fmt.Errorf("invalid range %q", rangeStr)
		}
		p.tier = t
		p.from = now.Add(-t.Window)
		p.to = now
		if fromStr != "" && toStr != "" {
			from, errF := strconv.ParseInt(fromStr, 10, 64)
			to, errT := strconv.ParseInt(toStr, 10, 64)
			if errF != nil || errT != nil {
				return historyParams{}, errors.New("invalid from/to")
			}
			if to-from > int64(t.Window.Seconds()) {
				return historyParams{}, fmt.Errorf("requested window > tier window (%s)", t.Name)
			}
			p.from = time.Unix(from, 0)
			p.to = time.Unix(to, 0)
		}
	} else {
		from, errF := strconv.ParseInt(fromStr, 10, 64)
		to, errT := strconv.ParseInt(toStr, 10, 64)
		if errF != nil || errT != nil {
			return historyParams{}, errors.New("invalid from/to")
		}
		if to <= from {
			return historyParams{}, errors.New("to must be > from")
		}
		span := time.Duration(to-from) * time.Second
		p.tier = persistence.SelectTier(tiers, span)
		p.from = time.Unix(from, 0)
		p.to = time.Unix(to, 0)
	}

	if sinceStr != "" {
		s, err := strconv.ParseInt(sinceStr, 10, 64)
		if err != nil {
			return historyParams{}, errors.New("invalid since")
		}
		// Strict: timestamp > since.
		p.from = time.Unix(s+1, 0)
		p.hasSince = true
		p.since = s
	}
	return p, nil
}

func tierByName(tiers []persistence.Tier, name string) (persistence.Tier, bool) {
	for _, t := range tiers {
		if t.Name == name {
			return t, true
		}
	}
	return persistence.Tier{}, false
}

// ServeContainer handles GET /api/stats/history/container.
func (h *HistoryHandler) ServeContainer(w http.ResponseWriter, r *http.Request) {
	p, err := parseHistoryParams(r.URL.Query(), h.tiers)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	containerID := r.URL.Query().Get("container_id")
	if containerID == "" {
		http.Error(w, "container_id required", http.StatusBadRequest)
		return
	}
	rows, err := h.db.QueryContainerHistory(
		r.Context(), containerID, p.tier.Name, p.from.Unix(), p.to.Unix())
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	resp := persistence.FillGaps(rows, p.tier, p.from, p.to)
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

// ServeHost handles GET /api/stats/history/host.
func (h *HistoryHandler) ServeHost(w http.ResponseWriter, r *http.Request) {
	p, err := parseHistoryParams(r.URL.Query(), h.tiers)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	hostID := r.URL.Query().Get("host_id")
	if hostID == "" {
		http.Error(w, "host_id required", http.StatusBadRequest)
		return
	}
	rows, err := h.db.QueryHostHistory(
		r.Context(), hostID, p.tier.Name, p.from.Unix(), p.to.Unix())
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	resp := persistence.FillGaps(rows, p.tier, p.from, p.to)
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}
