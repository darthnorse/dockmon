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
