package persistence

import (
	"testing"
	"time"
)

func TestSelectTier_ExactMatch(t *testing.T) {
	tiers := ComputeTiers(500)
	got := SelectTier(tiers, 1*time.Hour)
	if got.Name != "1h" {
		t.Errorf("got %q, want 1h", got.Name)
	}
}

func TestSelectTier_FallsThroughToLargest(t *testing.T) {
	tiers := ComputeTiers(500)
	got := SelectTier(tiers, 365*24*time.Hour)
	if got.Name != "30d" {
		t.Errorf("got %q, want 30d (largest tier)", got.Name)
	}
}

func TestSelectTier_PicksSmallestSufficient(t *testing.T) {
	tiers := ComputeTiers(500)
	// 5h fits in 8h
	got := SelectTier(tiers, 5*time.Hour)
	if got.Name != "8h" {
		t.Errorf("got %q, want 8h", got.Name)
	}
}

func TestFillGaps_AllPresent(t *testing.T) {
	// Tier with 1-second interval so all test timestamps align to whole seconds.
	tier := Tier{Name: "1h", Window: time.Hour, Interval: time.Second}
	from := time.Unix(100, 0)
	to := time.Unix(104, 0)
	rows := []HistoryRow{
		{Timestamp: 100, CPU: ptrF64(1)},
		{Timestamp: 101, CPU: ptrF64(2)},
		{Timestamp: 102, CPU: ptrF64(3)},
		{Timestamp: 103, CPU: ptrF64(4)},
		{Timestamp: 104, CPU: ptrF64(5)},
	}
	res := FillGaps(rows, tier, from, to)
	if len(res.Timestamps) != 5 {
		t.Fatalf("len(timestamps)=%d, want 5", len(res.Timestamps))
	}
	for i, v := range res.CPU {
		if v == nil {
			t.Errorf("CPU[%d] is nil, want non-nil", i)
		}
	}
}

func TestFillGaps_MissingMiddleProducesNull(t *testing.T) {
	tier := Tier{Name: "1h", Window: time.Hour, Interval: time.Second}
	from := time.Unix(100, 0)
	to := time.Unix(104, 0)
	rows := []HistoryRow{
		{Timestamp: 100, CPU: ptrF64(10)},
		{Timestamp: 102, CPU: ptrF64(20)},
		{Timestamp: 104, CPU: ptrF64(30)},
	}
	res := FillGaps(rows, tier, from, to)
	if len(res.Timestamps) != 5 {
		t.Fatalf("len=%d, want 5", len(res.Timestamps))
	}
	if res.CPU[1] != nil || res.CPU[3] != nil {
		t.Errorf("expected gaps at indices 1 and 3, got %v", res.CPU)
	}
	if res.CPU[0] == nil || *res.CPU[0] != 10 {
		t.Errorf("CPU[0] mismatch")
	}
}

func TestFillGaps_SubSecondInterval(t *testing.T) {
	// Fractional-second intervals: verify `from`/`to` are snapped and the grid
	// walks correctly. Tier 0 in production uses 7.2s intervals.
	tier := Tier{Name: "1h", Window: time.Hour, Interval: 7200 * time.Millisecond}
	from := time.Unix(0, 0)
	to := from.Add(36 * time.Second) // spans ~5 bucket boundaries: 0, 7.2, 14.4, 21.6, 28.8, 36.0
	rows := []HistoryRow{}
	res := FillGaps(rows, tier, from, to)
	if len(res.Timestamps) != 6 {
		t.Errorf("len(timestamps)=%d, want 6 (0, 7, 14, 21, 28, 36 truncated to unix seconds)",
			len(res.Timestamps))
	}
	// All CPU entries should be nil (no rows provided).
	for i, v := range res.CPU {
		if v != nil {
			t.Errorf("CPU[%d] should be nil, got %v", i, *v)
		}
	}
}

func ptrF64(v float64) *float64 { return &v }
