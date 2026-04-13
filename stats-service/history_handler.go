package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
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
	tier persistence.Tier
	from time.Time
	to   time.Time
}

// parseHistoryParams maps the query string to a normalized (tier, window) pair.
// Spec §9 'Query parameter semantics'.
func parseHistoryParams(q url.Values, tiers []persistence.Tier) (historyParams, error) {
	rangeStr := q.Get("range")
	fromStr := q.Get("from")
	toStr := q.Get("to")
	sinceStr := q.Get("since")

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
			from, to, err := parseFromTo(fromStr, toStr)
			if err != nil {
				return historyParams{}, err
			}
			if to-from > int64(t.Window.Seconds()) {
				return historyParams{}, fmt.Errorf("requested window > tier window (%s)", t.Name)
			}
			p.from = time.Unix(from, 0)
			p.to = time.Unix(to, 0)
		}
	} else {
		from, to, err := parseFromTo(fromStr, toStr)
		if err != nil {
			return historyParams{}, err
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
		// Snap forward to the next bucket boundary. A naive +1s is
		// insufficient when bucket intervals have fractional seconds
		// (e.g. 7.2s at default pointsPerView=500): the +1 lands inside
		// the same bucket, causing FillGaps to re-emit it as a null gap.
		candidate := time.Unix(s+1, 0)
		bucket := candidate.Truncate(p.tier.Interval)
		if bucket.Before(candidate) {
			candidate = bucket.Add(p.tier.Interval)
		}
		if candidate.After(p.to) {
			p.from = p.to
		} else {
			p.from = candidate
		}
	}
	return p, nil
}

// parseFromTo parses the from/to query pair and enforces from < to. The
// inequality is strict because a zero-width window would produce a single
// bucket at bucket-boundary truncation, which has no meaningful semantic
// for either incremental polling or canned-range display.
func parseFromTo(fromStr, toStr string) (int64, int64, error) {
	from, errF := strconv.ParseInt(fromStr, 10, 64)
	to, errT := strconv.ParseInt(toStr, 10, 64)
	if errF != nil || errT != nil {
		return 0, 0, errors.New("invalid from/to")
	}
	if to <= from {
		return 0, 0, errors.New("to must be > from")
	}
	return from, to, nil
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
	if !isGet(w, r) {
		return
	}
	q := r.URL.Query()
	p, err := parseHistoryParams(q, h.tiers)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	containerID := q.Get("container_id")
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
	writeJSON(w, persistence.FillGaps(rows, p.tier, p.from, p.to))
}

// ServeHost handles GET /api/stats/history/host.
func (h *HistoryHandler) ServeHost(w http.ResponseWriter, r *http.Request) {
	if !isGet(w, r) {
		return
	}
	q := r.URL.Query()
	p, err := parseHistoryParams(q, h.tiers)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	hostID := q.Get("host_id")
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
	writeJSON(w, persistence.FillGaps(rows, p.tier, p.from, p.to))
}

// isGet rejects non-GET methods with 405. Returns true if the request can
// proceed. Sets the Allow header on rejection so clients see the expected
// method per RFC 9110 §15.5.6.
func isGet(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", http.MethodGet)
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return false
	}
	return true
}

// writeJSON sets the content-type and encodes the response. Encode errors
// are ignored because the body is already committed by the time they can
// fail — nothing actionable remains to report to the client.
func writeJSON(w http.ResponseWriter, resp persistence.HistoryResponse) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}
