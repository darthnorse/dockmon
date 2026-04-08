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

// sample is one observation fed into the cascade. Container samples leave
// host-only fields (ContainerCount) zero; the writer ignores them.
type sample struct {
	CPU            float64
	MemPercent     float64
	MemUsed        uint64
	MemLimit       uint64 // config, not blended — last non-zero wins
	NetBps         float64
	ContainerCount int // host-only snapshot, not blended — last value wins
}

// blend computes the per-bucket aggregate using a MAX/AVG mix:
//
//	value = alpha*max(samples) + (1-alpha)*avg(samples)
//
// MemLimit and ContainerCount bypass the blend (config / snapshot data).
// Empty input → NaN for float fields; the writer translates NaN to SQL NULL.
func blend(samples []sample, alpha float64) sample {
	if len(samples) == 0 {
		nan := math.NaN()
		return sample{CPU: nan, MemPercent: nan, NetBps: nan}
	}
	return sample{
		CPU:            blendField(samples, alpha, func(s sample) float64 { return s.CPU }),
		MemPercent:     blendField(samples, alpha, func(s sample) float64 { return s.MemPercent }),
		MemUsed:        blendUint(samples, alpha, func(s sample) uint64 { return s.MemUsed }),
		MemLimit:       lastNonZeroLimit(samples),
		NetBps:         blendField(samples, alpha, func(s sample) float64 { return s.NetBps }),
		ContainerCount: lastContainerCount(samples),
	}
}

// blendField computes alpha*max + (1-alpha)*avg for a float64 field.
// Local names are maxV/sumV (not max/sum) so we do not shadow the Go 1.21+
// built-in max, which would make future refactors to `max(a, b)` subtly wrong.
func blendField(samples []sample, alpha float64, get func(sample) float64) float64 {
	maxV := math.Inf(-1)
	var sumV float64
	for _, s := range samples {
		v := get(s)
		if v > maxV {
			maxV = v
		}
		sumV += v
	}
	avg := sumV / float64(len(samples))
	return alpha*maxV + (1-alpha)*avg
}

// blendUint is the uint64 variant for memory byte counts.
//
// Overflow bound on sumV: a single bucket holds at most one sample per
// source per second. The largest tier 0 bucket is 7.2s, and higher tiers
// cascade already-blended parent values (n ≈ 8 on cascade-up), so len is
// small (≤ ~10 in practice). Even at an implausible 1 TB/sample, sumV
// stays well under uint64 max (≈1.8e19). No overflow guard needed.
func blendUint(samples []sample, alpha float64, get func(sample) uint64) uint64 {
	var maxV, sumV uint64
	for _, s := range samples {
		v := get(s)
		if v > maxV {
			maxV = v
		}
		sumV += v
	}
	avg := float64(sumV) / float64(len(samples))
	return uint64(alpha*float64(maxV) + (1-alpha)*avg)
}

// lastNonZeroLimit returns the most recent non-zero memory limit from the
// samples. MemLimit is configuration, not a metric — blending it produces
// nonsense. Returning the latest non-zero value preserves the observed
// limit even if the final sample reports zero (e.g., container removed).
func lastNonZeroLimit(samples []sample) uint64 {
	for i := len(samples) - 1; i >= 0; i-- {
		if samples[i].MemLimit > 0 {
			return samples[i].MemLimit
		}
	}
	return 0
}

// lastContainerCount returns the most recent container count snapshot.
// Averaging would smooth meaningful step changes.
func lastContainerCount(samples []sample) int {
	if len(samples) == 0 {
		return 0
	}
	return samples[len(samples)-1].ContainerCount
}
