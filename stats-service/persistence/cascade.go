package persistence

import (
	"log"
	"math"
	"strings"
	"sync"
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

// blendNumber constrains the numeric field types blendCore can operate on:
// float64 for ratios/rates and uint64 for byte counts.
type blendNumber interface {
	~float64 | ~uint64
}

// blendCore walks samples once, computing alpha*max + (1-alpha)*avg in
// float64 space. Callers supply the identity value for max (math.Inf(-1)
// for float64, 0 for uint64) and cast the returned float64 back to their
// field type as needed.
//
// Local names are maxV/sumV (not max/sum) so we do not shadow the Go 1.21+
// built-in max, which would make future refactors to `max(a, b)` subtly wrong.
//
// Overflow bound on sumV for the uint64 path: a single bucket holds at most
// one sample per source per second. The largest tier 0 bucket is 7.2s, and
// higher tiers cascade already-blended parent values (n ≈ 8 on cascade-up),
// so len is small (≤ ~10 in practice). Even at an implausible 1 TB/sample,
// sumV stays well under uint64 max (≈1.8e19). No overflow guard needed.
func blendCore[T blendNumber](samples []sample, alpha float64, maxInit T, get func(sample) T) float64 {
	maxV := maxInit
	var sumV T
	for _, s := range samples {
		v := get(s)
		if v > maxV {
			maxV = v
		}
		sumV += v
	}
	avg := float64(sumV) / float64(len(samples))
	return alpha*float64(maxV) + (1-alpha)*avg
}

// blendField computes the blend for a float64 field.
func blendField(samples []sample, alpha float64, get func(sample) float64) float64 {
	return blendCore(samples, alpha, math.Inf(-1), get)
}

// blendUint is the uint64 variant for memory byte counts.
func blendUint(samples []sample, alpha float64, get func(sample) uint64) uint64 {
	return uint64(blendCore(samples, alpha, uint64(0), get))
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

// entityKey identifies one (entity, tier) slot in the cascade's state map.
type entityKey struct {
	entityID string
	tierIdx  int
}

// tierState is the accumulating bucket for one (entity, tier).
// A zero-valued tierState (bucketTs.IsZero()) represents "no bucket in flight."
type tierState struct {
	bucketTs time.Time
	isHost   bool // remembered from first ingest so cascade-up can carry it
	accum    []sample
}

// writeJob is the unit of work the writer goroutine consumes.
type writeJob struct {
	tier     string // "1h" | "8h" | "24h" | "7d" | "30d"
	isHost   bool
	entityID string    // composite container key OR host_id
	ts       time.Time // bucket start (quantized)
	value    sample
}

// Cascade owns in-memory bucket state for every (entity, tier) pair and emits
// writeJobs to its writer channel as buckets cross their boundaries.
//
// State lifetime: entries in the state map are created on first Ingest for a
// given (entity, tier) and overwritten in place on every bucket finalization;
// they are never deleted by Ingest itself. An entity that stops emitting
// samples leaves its last-in-flight bucket in the map indefinitely. Explicit
// cleanup for long-gone entities is the caller's responsibility (see Task 8's
// RemoveHost). This is an intentional design trade-off: finalize vs. cleanup
// is ambiguous without upstream lifecycle signals, so the cascade avoids
// guessing and relies on the aggregator to tell it when an entity is gone.
type Cascade struct {
	tiers  []Tier
	state  map[entityKey]tierState
	writes chan<- writeJob
	mu     sync.Mutex
}

// NewCascade builds a fresh cascade.
func NewCascade(tiers []Tier, writes chan<- writeJob) *Cascade {
	return &Cascade{
		tiers:  tiers,
		state:  make(map[entityKey]tierState),
		writes: writes,
	}
}

// Ingest delivers one raw sample for one entity at one wall-clock time.
// Raw samples only feed tier 0; cascade-up propagates inside feedTier when
// a bucket boundary is crossed.
func (c *Cascade) Ingest(entityID string, isHost bool, sampleTs time.Time, val sample) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.feedTier(entityID, isHost, 0, sampleTs, val)
}

// feedTier processes exactly ONE (entityID, tierIdx) — spec §5 invariant.
// Raw samples enter at tierIdx=0 via Ingest. When a bucket fires, the blend
// is cascade-fed to tierIdx+1 using the OLD bucket's ts (not sampleTs), so
// each tier's grid is anchored to the tier below it, which is anchored to
// the universal Unix-epoch grid.
func (c *Cascade) feedTier(
	entityID string, isHost bool, tierIdx int, sampleTs time.Time, val sample,
) {
	if tierIdx >= len(c.tiers) {
		return
	}
	tier := c.tiers[tierIdx]
	bts := sampleTs.Truncate(tier.Interval)
	key := entityKey{entityID, tierIdx}
	st := c.state[key]

	if !st.bucketTs.IsZero() && bts.After(st.bucketTs) {
		agg := blend(st.accum, tier.Alpha)
		// Non-blocking send: if the writer channel is full we drop the
		// finalized bucket and log a warning. Spec §7: dropping a bucket
		// becomes a chart null, recoverable on the next cycle — preferable
		// to blocking the stats cache ingestion path, which would stall
		// every other entity behind this mutex.
		select {
		case c.writes <- writeJob{
			tier:     tier.Name,
			isHost:   st.isHost,
			entityID: entityID,
			ts:       st.bucketTs,
			value:    agg,
		}:
		default:
			log.Printf("Cascade: writes channel full, dropping %s bucket for %s at %s",
				tier.Name, entityID, st.bucketTs.Format(time.RFC3339))
		}
		c.feedTier(entityID, isHost, tierIdx+1, st.bucketTs, agg)
		st = tierState{}
	}
	if st.bucketTs.IsZero() {
		st.bucketTs = bts
		st.isHost = isHost
	}
	st.accum = append(st.accum, val)
	c.state[key] = st
}

// RemoveHost drops all in-memory state for the given host: both the host
// row itself and any container rows whose composite key is "<hostID>:...".
// Called from the host-removal flow after StatsCache cleanup so the cascade
// stops emitting writes for a host whose DB rows are about to cascade-delete.
func (c *Cascade) RemoveHost(hostID string) {
	prefix := hostID + ":"
	c.mu.Lock()
	defer c.mu.Unlock()
	for k := range c.state {
		if k.entityID == hostID || strings.HasPrefix(k.entityID, prefix) {
			delete(c.state, k)
		}
	}
}
