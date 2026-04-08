package persistence

import "time"

// HistoryResponse is the column-major shape returned by the read endpoints.
// Column-major is the native format StatsCharts consumes on the frontend —
// row-major would need a transform at every call. See spec §9 'Response shape'.
type HistoryResponse struct {
	Tier            string     `json:"tier"`
	TierSeconds     int64      `json:"tier_seconds"`
	IntervalSeconds int64      `json:"interval_seconds"`
	From            int64      `json:"from"`
	To              int64      `json:"to"`
	ServerTime      int64      `json:"server_time"`
	Timestamps      []int64    `json:"timestamps"`
	CPU             []*float64 `json:"cpu"`
	Mem             []*float64 `json:"mem"`
	MemUsedBytes    []*int64   `json:"memory_used_bytes,omitempty"`
	MemLimitBytes   []*int64   `json:"memory_limit_bytes,omitempty"`
	NetBps          []*float64 `json:"net_bps"`
	ContainerCount  []*int     `json:"container_count,omitempty"`
}

// SelectTier picks the smallest tier whose Window is at least the given duration.
// Falls through to the largest tier if no tier is large enough.
func SelectTier(tiers []Tier, want time.Duration) Tier {
	for _, t := range tiers {
		if t.Window >= want {
			return t
		}
	}
	return tiers[len(tiers)-1]
}

// FillGaps walks the bucket grid from `from` to `to` (inclusive) at tier.Interval
// step, emitting one slot per expected bucket and pulling row data when present.
// Missing buckets become null entries (chart gaps).
//
// `from` and `to` are snapped to bucket boundaries before walking the grid; the
// response's From/To reflect the snapped values so the caller can't see a
// mismatch between their requested window and the returned timestamps.
func FillGaps(rows []HistoryRow, tier Tier, from, to time.Time) HistoryResponse {
	fromBucket := from.Truncate(tier.Interval)
	toBucket := to.Truncate(tier.Interval)
	intervalSec := int64(tier.Interval.Seconds())
	if intervalSec < 1 {
		intervalSec = 1
	}

	byTs := make(map[int64]HistoryRow, len(rows))
	for _, r := range rows {
		byTs[r.Timestamp] = r
	}

	res := HistoryResponse{
		Tier:            tier.Name,
		TierSeconds:     int64(tier.Window.Seconds()),
		IntervalSeconds: intervalSec,
		From:            fromBucket.Unix(),
		To:              toBucket.Unix(),
		ServerTime:      time.Now().Unix(),
	}

	for ts := fromBucket; !ts.After(toBucket); ts = ts.Add(tier.Interval) {
		unix := ts.Unix()
		res.Timestamps = append(res.Timestamps, unix)
		if r, ok := byTs[unix]; ok {
			res.CPU = append(res.CPU, r.CPU)
			res.Mem = append(res.Mem, r.MemPercent)
			res.MemUsedBytes = append(res.MemUsedBytes, r.MemUsed)
			res.MemLimitBytes = append(res.MemLimitBytes, r.MemLimit)
			res.NetBps = append(res.NetBps, r.NetBps)
			res.ContainerCount = append(res.ContainerCount, r.ContainerCount)
		} else {
			res.CPU = append(res.CPU, nil)
			res.Mem = append(res.Mem, nil)
			res.MemUsedBytes = append(res.MemUsedBytes, nil)
			res.MemLimitBytes = append(res.MemLimitBytes, nil)
			res.NetBps = append(res.NetBps, nil)
			res.ContainerCount = append(res.ContainerCount, nil)
		}
	}
	return res
}
