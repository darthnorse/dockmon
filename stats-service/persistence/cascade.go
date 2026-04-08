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
func ComputeTiers(pointsPerView int) []Tier {
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
