package persistence

import (
	"math"
	"testing"
	"time"
)

func TestComputeTiers_DefaultPointsPerView(t *testing.T) {
	tiers := ComputeTiers(500)
	if len(tiers) != 5 {
		t.Fatalf("len=%d, want 5", len(tiers))
	}

	wantNames := []string{"1h", "8h", "24h", "7d", "30d"}
	for i, w := range wantNames {
		if tiers[i].Name != w {
			t.Errorf("tiers[%d].Name=%q, want %q", i, tiers[i].Name, w)
		}
	}

	wantIntervals := []time.Duration{
		7200 * time.Millisecond,
		57600 * time.Millisecond,
		172800 * time.Millisecond,
		1209600 * time.Millisecond,
		5184 * time.Second,
	}
	for i, w := range wantIntervals {
		if tiers[i].Interval != w {
			t.Errorf("tiers[%d].Interval=%v, want %v", i, tiers[i].Interval, w)
		}
	}

	wantAlphas := []float64{0.75, 0.50, 0.25, 0.0, 0.0}
	for i, w := range wantAlphas {
		if math.Abs(tiers[i].Alpha-w) > 1e-9 {
			t.Errorf("tiers[%d].Alpha=%v, want %v", i, tiers[i].Alpha, w)
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
