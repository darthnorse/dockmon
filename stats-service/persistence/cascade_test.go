package persistence

import (
	"fmt"
	"math"
	"testing"
	"time"
)

func TestComputeTiers_DefaultPointsPerView(t *testing.T) {
	want := []struct {
		name     string
		interval time.Duration
		alpha    float64
	}{
		{"1h", 7200 * time.Millisecond, 0.75},
		{"8h", 57600 * time.Millisecond, 0.50},
		{"24h", 172800 * time.Millisecond, 0.25},
		{"7d", 1209600 * time.Millisecond, 0.0},
		{"30d", 5184 * time.Second, 0.0},
	}

	got := ComputeTiers(500)
	if len(got) != len(want) {
		t.Fatalf("len=%d, want %d", len(got), len(want))
	}
	for i, w := range want {
		if got[i].Name != w.name {
			t.Errorf("tiers[%d].Name=%q, want %q", i, got[i].Name, w.name)
		}
		if got[i].Interval != w.interval {
			t.Errorf("tiers[%d].Interval=%v, want %v", i, got[i].Interval, w.interval)
		}
		if math.Abs(got[i].Alpha-w.alpha) > 1e-9 {
			t.Errorf("tiers[%d].Alpha=%v, want %v", i, got[i].Alpha, w.alpha)
		}
	}
}

func TestComputeTiers_FloorAtOneSecond(t *testing.T) {
	tiers := ComputeTiers(100000)
	if tiers[0].Interval != time.Second {
		t.Errorf("tiers[0].Interval=%v, want 1s (clamped)", tiers[0].Interval)
	}
}

func TestComputeTiers_HigherTiersAreMultiplesOfTier0(t *testing.T) {
	// Critical invariant: tier N+1 interval must be an integer multiple of
	// tier N interval, so cascade-up's bucketTs alignment holds.
	tiers := ComputeTiers(500)
	for i := 1; i < len(tiers); i++ {
		ratio := tiers[i].Interval / tiers[0].Interval
		expected := time.Duration(ratio) * tiers[0].Interval
		if tiers[i].Interval != expected {
			t.Errorf("tier[%d] interval %v not a multiple of tier[0] %v",
				i, tiers[i].Interval, tiers[0].Interval)
		}
	}
}

func TestComputeTiers_PanicsOnNonPositivePointsPerView(t *testing.T) {
	// Guard against a cryptic runtime "integer divide by zero" (for 0) or
	// nonsense all-1s tiers (for negatives). Upstream config validation
	// enforces floor=100, ceiling=2000; this is a fail-fast safety net.
	for _, n := range []int{0, -1, -500} {
		t.Run(fmt.Sprintf("n=%d", n), func(t *testing.T) {
			defer func() {
				if r := recover(); r == nil {
					t.Errorf("ComputeTiers(%d) did not panic", n)
				}
			}()
			_ = ComputeTiers(n)
		})
	}
}

func TestBlend_PureMaxAtAlpha1(t *testing.T) {
	samples := []sample{
		{CPU: 10, MemPercent: 20, MemUsed: 1000, MemLimit: 5000, NetBps: 100},
		{CPU: 50, MemPercent: 30, MemUsed: 2000, MemLimit: 5000, NetBps: 200},
		{CPU: 30, MemPercent: 25, MemUsed: 1500, MemLimit: 5000, NetBps: 150},
	}
	got := blend(samples, 1.0)
	if got.CPU != 50 {
		t.Errorf("CPU=%v, want 50 (max)", got.CPU)
	}
	if got.NetBps != 200 {
		t.Errorf("NetBps=%v, want 200 (max)", got.NetBps)
	}
}

func TestBlend_PureAvgAtAlpha0(t *testing.T) {
	samples := []sample{
		{CPU: 10},
		{CPU: 50},
		{CPU: 30},
	}
	got := blend(samples, 0.0)
	want := 30.0
	if math.Abs(got.CPU-want) > 1e-9 {
		t.Errorf("CPU=%v, want %v (avg)", got.CPU, want)
	}
}

func TestBlend_75_25Mix(t *testing.T) {
	// max=50, avg=30, 0.75*50 + 0.25*30 = 37.5 + 7.5 = 45
	samples := []sample{{CPU: 10}, {CPU: 50}, {CPU: 30}}
	got := blend(samples, 0.75)
	if math.Abs(got.CPU-45.0) > 1e-9 {
		t.Errorf("CPU=%v, want 45", got.CPU)
	}
}

func TestBlend_EmptyReturnsNaN(t *testing.T) {
	got := blend(nil, 0.5)
	if !math.IsNaN(got.CPU) {
		t.Errorf("expected NaN for empty, got %v", got.CPU)
	}
}

func TestBlend_MemLimitIsLastNonZero(t *testing.T) {
	samples := []sample{
		{MemLimit: 1000},
		{MemLimit: 2000},
		{MemLimit: 0}, // ignored
	}
	got := blend(samples, 0.5)
	if got.MemLimit != 2000 {
		t.Errorf("MemLimit=%d, want 2000", got.MemLimit)
	}
}

func TestBlend_ContainerCountIsLast(t *testing.T) {
	samples := []sample{
		{ContainerCount: 5},
		{ContainerCount: 10},
		{ContainerCount: 7},
	}
	got := blend(samples, 0.5)
	if got.ContainerCount != 7 {
		t.Errorf("ContainerCount=%d, want 7", got.ContainerCount)
	}
}

func TestBlend_PureAvgAtAlpha0_UintField(t *testing.T) {
	// Symmetric coverage with TestBlend_PureAvgAtAlpha0, but for the uint path:
	// alpha=0 on MemUsed must be pure average, not max.
	// avg(1000, 2000, 1500) = 1500
	samples := []sample{
		{MemUsed: 1000},
		{MemUsed: 2000},
		{MemUsed: 1500},
	}
	got := blend(samples, 0.0)
	if got.MemUsed != 1500 {
		t.Errorf("MemUsed=%d, want 1500 (avg)", got.MemUsed)
	}
}

func TestBlend_SingleSampleBucket(t *testing.T) {
	// A one-sample bucket must be idempotent: for any alpha, the result
	// equals the input sample for every blended field. max == avg, so
	// alpha*max + (1-alpha)*avg == max for all alpha.
	s := sample{
		CPU:            42.5,
		MemPercent:     17.25,
		MemUsed:        123456789,
		MemLimit:       987654321,
		NetBps:         5000,
		ContainerCount: 3,
	}
	for _, alpha := range []float64{0.0, 0.25, 0.5, 0.75, 1.0} {
		got := blend([]sample{s}, alpha)
		if got.CPU != s.CPU {
			t.Errorf("alpha=%v CPU=%v, want %v", alpha, got.CPU, s.CPU)
		}
		if got.MemPercent != s.MemPercent {
			t.Errorf("alpha=%v MemPercent=%v, want %v", alpha, got.MemPercent, s.MemPercent)
		}
		if got.MemUsed != s.MemUsed {
			t.Errorf("alpha=%v MemUsed=%d, want %d", alpha, got.MemUsed, s.MemUsed)
		}
		if got.MemLimit != s.MemLimit {
			t.Errorf("alpha=%v MemLimit=%d, want %d", alpha, got.MemLimit, s.MemLimit)
		}
		if got.NetBps != s.NetBps {
			t.Errorf("alpha=%v NetBps=%v, want %v", alpha, got.NetBps, s.NetBps)
		}
		if got.ContainerCount != s.ContainerCount {
			t.Errorf("alpha=%v ContainerCount=%d, want %d", alpha, got.ContainerCount, s.ContainerCount)
		}
	}
}

func TestBlend_MemLimitAllZeroReturnsZero(t *testing.T) {
	// When every sample in the bucket reports MemLimit=0 (no observed
	// limit — e.g., unlimited container, or metric not yet populated),
	// lastNonZeroLimit returns 0. Writer's nullIfZeroU64 will translate
	// this to SQL NULL downstream.
	samples := []sample{
		{MemLimit: 0, CPU: 10},
		{MemLimit: 0, CPU: 20},
	}
	got := blend(samples, 0.5)
	if got.MemLimit != 0 {
		t.Errorf("MemLimit=%d, want 0 (all-zero bucket)", got.MemLimit)
	}
}

func TestBucketQuantization_SubSecondInterval(t *testing.T) {
	// Tier 0 interval is 7.2s. time.Truncate floors the Unix-epoch duration
	// to the largest multiple of the interval that is <= ts.
	// 10000.5s / 7.2s ≈ 1388.958 → floor = 1388 → 1388 * 7.2 = 9993.6s
	// = 9_993_600_000_000 ns.
	interval := 7200 * time.Millisecond
	ts := time.Unix(10000, 500_000_000) // 10000.5s
	bucket := ts.Truncate(interval)
	wantUnixNs := int64(9_993_600_000_000)
	if bucket.UnixNano() != wantUnixNs {
		t.Errorf("bucket=%v (unix=%d ns), want unix=%d ns",
			bucket, bucket.UnixNano(), wantUnixNs)
	}
}
