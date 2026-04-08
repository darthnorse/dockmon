package persistence

import (
	"math"
	"time"
)

// Tier describes one resolution level in the RRD-style cascade.
// See spec §4 for the model.
type Tier struct {
	Name     string        // "1h" | "8h" | "24h" | "7d" | "30d"
	Window   time.Duration // total time the tier covers
	Interval time.Duration // bucket size = max(window/points_per_view, 1s)
	Alpha    float64       // MAX/AVG blend coefficient: max(0, 0.75-i*0.25)
}

// ComputeTiers builds the 5-tier definition for the given points_per_view.
// Default is 500. Higher values increase resolution per tier but grow
// in-memory cascade state and disk rows per series proportionally.
//
// Precondition: pointsPerView must be > 0. Config validation upstream
// enforces a floor of 100 and ceiling of 2000 (spec §17); a zero or
// negative value here indicates a programming error and panics fast
// rather than producing a cryptic "integer divide by zero" deeper in
// the call stack.
//
// Fractional-second intervals are intentional. At pointsPerView=500 the
// tier 0 bucket is 7.2s, which deliberately does NOT align with wall-clock
// seconds — time.Truncate floors to multiples of the interval measured
// from the Unix epoch. Higher tiers are integer multiples of tier 0's
// interval (tier 1 = 8 × tier 0, tier 2 = 24 × tier 0, etc.), which is
// what lets cascade-up reuse the parent tier's bucketTs without drifting
// off the universal grid. Do NOT "round" the intervals to whole seconds:
// it would break that alignment guarantee. See spec §4 and §5.
func ComputeTiers(pointsPerView int) []Tier {
	if pointsPerView <= 0 {
		panic("persistence: ComputeTiers requires pointsPerView > 0")
	}
	views := []struct {
		name   string
		window time.Duration
	}{
		{"1h", 1 * time.Hour},
		{"8h", 8 * time.Hour},
		{"24h", 24 * time.Hour},
		{"7d", 7 * 24 * time.Hour},
		{"30d", 30 * 24 * time.Hour},
	}
	tiers := make([]Tier, len(views))
	for i, v := range views {
		// Floor at 1s: for very large pointsPerView, the 1h tier would
		// otherwise drop below a second (e.g. pointsPerView=100000 yields
		// 36ms), which is finer than our 1s sample cadence can feed.
		interval := v.window / time.Duration(pointsPerView)
		if interval < time.Second {
			interval = time.Second
		}
		tiers[i] = Tier{
			Name:     v.name,
			Window:   v.window,
			Interval: interval,
			Alpha:    math.Max(0, 0.75-float64(i)*0.25),
		}
	}
	return tiers
}
