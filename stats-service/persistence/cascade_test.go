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
	// Every tier's interval must be an integer multiple of tier 0's interval
	// at the default pointsPerView=500. This is not strictly required for
	// cascade correctness — each tier independently re-truncates to the
	// Unix-epoch grid in feedTier — but it keeps bucket counts per cascade-up
	// predictable and makes the blend math reason about integer sample counts
	// instead of fractional boundaries. Note this only holds tier-N-vs-tier-0;
	// adjacent tiers need not be multiples of each other (e.g. at pps=500,
	// 30d/7d ≈ 4.286).
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
	samples := []Sample{
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
	samples := []Sample{
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
	samples := []Sample{{CPU: 10}, {CPU: 50}, {CPU: 30}}
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
	samples := []Sample{
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
	samples := []Sample{
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
	samples := []Sample{
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
	s := Sample{
		CPU:            42.5,
		MemPercent:     17.25,
		MemUsed:        123456789,
		MemLimit:       987654321,
		NetBps:         5000,
		ContainerCount: 3,
	}
	for _, alpha := range []float64{0.0, 0.25, 0.5, 0.75, 1.0} {
		got := blend([]Sample{s}, alpha)
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
	samples := []Sample{
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

// newTestCascade builds a Cascade wired to a buffered test channel.
// Returns the cascade, its writes channel, and the tier table the cascade
// was built from (callers often need tiers[0].Interval for bucket math).
func newTestCascade(bufSize int) (*Cascade, chan WriteJob, []Tier) {
	tiers := ComputeTiers(500)
	writes := make(chan WriteJob, bufSize)
	return NewCascade(tiers, writes), writes, tiers
}

// drainAll synchronously collects everything currently buffered on the channel.
func drainAll(ch chan WriteJob) []WriteJob {
	var out []WriteJob
	for {
		select {
		case j := <-ch:
			out = append(out, j)
		default:
			return out
		}
	}
}

// findJob returns the first job matching tier and entityID, or nil.
func findJob(jobs []WriteJob, tier, entityID string) *WriteJob {
	for i := range jobs {
		if jobs[i].tier == tier && jobs[i].entityID == entityID {
			return &jobs[i]
		}
	}
	return nil
}

func TestCascade_NoEmissionWithinSameBucket(t *testing.T) {
	c, writes, tiers := newTestCascade(64)

	// Align t0 to a tier-0 bucket boundary (7.2s) so all three samples
	// below fall inside the same bucket. time.Unix(1_000_000,0) lands
	// 6.4s into a bucket, so the +1s / +2s samples would cross into the
	// next bucket — not what this test wants to assert.
	t0 := time.Unix(1_000_000, 0).Truncate(tiers[0].Interval)
	c.Ingest("c1", false, t0, Sample{CPU: 10})
	c.Ingest("c1", false, t0.Add(1*time.Second), Sample{CPU: 20})
	c.Ingest("c1", false, t0.Add(2*time.Second), Sample{CPU: 30})

	got := drainAll(writes)
	if len(got) != 0 {
		t.Errorf("got %d writes within one bucket, want 0", len(got))
	}
}

func TestCascade_EmitsOnBucketBoundary(t *testing.T) {
	c, writes, _ := newTestCascade(64)

	// Tier 0 interval = 7.2s. Pick timestamps that cross a tier-0 boundary.
	base := time.Unix(0, 0).Add(7200 * time.Millisecond)
	c.Ingest("c1", false, base, Sample{CPU: 10})
	c.Ingest("c1", false, base.Add(8*time.Second), Sample{CPU: 50})

	jobs := drainAll(writes)
	tier0 := findJob(jobs, "1h", "c1")
	if tier0 == nil {
		t.Fatalf("expected a tier 1h write for c1, got %v", jobs)
	}
	if tier0.value.CPU != 10 {
		t.Errorf("tier0 finalized CPU=%v, want 10 (the only sample in that bucket)", tier0.value.CPU)
	}
}

func TestCascade_CascadeUpUsesBucketTsNotSampleTs(t *testing.T) {
	// Tier 0 = 7.2s, Tier 1 = 57.6s (8 × tier 0). Push enough tier-0 samples
	// that tier 1 eventually fires. Every tier 1 write timestamp must be
	// aligned to 57.6s exactly.
	c, writes, _ := newTestCascade(1024)

	base := time.Unix(0, 0)
	for i := 0; i < 100; i++ {
		ts := base.Add(time.Duration(i) * 8 * time.Second)
		c.Ingest("c1", false, ts, Sample{CPU: float64(i)})
	}

	for _, j := range drainAll(writes) {
		if j.tier != "8h" {
			continue
		}
		if j.ts.UnixNano()%int64(57600*time.Millisecond) != 0 {
			t.Errorf("8h tier write ts=%v not aligned to 57.6s", j.ts)
		}
	}
}

func TestCascade_FeedsTier0OnlyFromIngest(t *testing.T) {
	c, _, tiers := newTestCascade(64)

	c.Ingest("c1", false, time.Unix(1_000_000, 0), Sample{CPU: 42})

	c.mu.Lock()
	defer c.mu.Unlock()
	for tierIdx, tierDef := range tiers {
		st := c.state[entityKey{"c1", tierIdx}]
		if tierIdx == 0 && len(st.accum) != 1 {
			t.Errorf("tier 0 accum=%d, want 1", len(st.accum))
			continue
		}
		if tierIdx > 0 && len(st.accum) != 0 {
			t.Errorf("tier %d (%s) accum=%d, want 0 (only tier 0 receives raw samples)",
				tierIdx, tierDef.Name, len(st.accum))
		}
	}
}

func TestCascade_CrossEntityIsolation(t *testing.T) {
	// Two entities advancing through buckets in lockstep must not affect
	// each other's state: each gets its own tierState in the map and each
	// finalized bucket belongs to exactly the entity that produced it.
	c, writes, _ := newTestCascade(64)

	t0 := time.Unix(0, 0)
	// First bucket: one sample per entity inside tier-0 bucket 0.
	c.Ingest("c1", false, t0, Sample{CPU: 10})
	c.Ingest("c2", false, t0, Sample{CPU: 99})
	// Second bucket: one sample per entity in tier-0 bucket 1, which
	// finalizes each entity's bucket-0 tier-0 write independently.
	next := t0.Add(8 * time.Second)
	c.Ingest("c1", false, next, Sample{CPU: 20})
	c.Ingest("c2", false, next, Sample{CPU: 88})

	jobs := drainAll(writes)
	c1Tier0 := findJob(jobs, "1h", "c1")
	c2Tier0 := findJob(jobs, "1h", "c2")
	if c1Tier0 == nil || c2Tier0 == nil {
		t.Fatalf("expected a 1h write for both c1 and c2, got %+v", jobs)
	}
	if c1Tier0.value.CPU != 10 {
		t.Errorf("c1 tier0 CPU=%v, want 10 (c2's 99 must not leak in)", c1Tier0.value.CPU)
	}
	if c2Tier0.value.CPU != 99 {
		t.Errorf("c2 tier0 CPU=%v, want 99 (c1's 10 must not leak in)", c2Tier0.value.CPU)
	}
}

func TestCascade_IsHostPropagatesToWriteJob(t *testing.T) {
	// A host entity (isHost=true) must carry isHost=true through to every
	// WriteJob it produces, including those emitted by cascade-up to higher
	// tiers. Regression guard for the remembered-isHost contract in tierState.
	c, writes, _ := newTestCascade(1024)

	base := time.Unix(0, 0)
	// Feed enough tier-0 buckets to guarantee a tier-1 cascade-up fires.
	for i := 0; i < 20; i++ {
		ts := base.Add(time.Duration(i) * 8 * time.Second)
		c.Ingest("host-a", true, ts, Sample{CPU: float64(i), ContainerCount: 5})
	}

	jobs := drainAll(writes)
	if len(jobs) == 0 {
		t.Fatalf("expected at least one host write, got none")
	}
	sawTier1 := false
	for _, j := range jobs {
		if j.entityID != "host-a" {
			t.Errorf("unexpected entityID %q on host write", j.entityID)
		}
		if !j.isHost {
			t.Errorf("tier %s write for host-a has isHost=false, want true", j.tier)
		}
		if j.tier == "8h" {
			sawTier1 = true
		}
	}
	if !sawTier1 {
		t.Errorf("expected cascade-up to produce at least one 8h write, got %d jobs at other tiers", len(jobs))
	}
}

func TestCascade_RestartIsClean(t *testing.T) {
	// A fresh cascade after "restart" receiving a sample within the same tier-0
	// bucket window must NOT produce a duplicate write for the bucket before restart.
	c1, _, _ := newTestCascade(64)
	c1.Ingest("c1", false, time.Unix(1_000_000, 0), Sample{CPU: 10})

	c2, writes2, _ := newTestCascade(64)
	c2.Ingest("c1", false, time.Unix(1_000_007, 0), Sample{CPU: 20})
	got := drainAll(writes2)
	if len(got) != 0 {
		t.Errorf("expected no writes after restart with samples in same bucket, got %v", got)
	}
}

func TestCascade_RemoveHost(t *testing.T) {
	// Happy path: populate state for two hosts and their containers,
	// remove host-1, verify host-1's entries are gone and host-2's remain.
	// Assertions enumerate exact keys rather than re-implementing the
	// predicate RemoveHost uses, so a regression in that predicate cannot
	// be mirrored (and hidden) by identical test logic.
	c, _, _ := newTestCascade(64)
	now := time.Unix(1_000_000, 0)

	c.Ingest("host-1:abc123def456", false, now, Sample{CPU: 1})
	c.Ingest("host-1:def456abc123", false, now, Sample{CPU: 2})
	c.Ingest("host-2:fedcba987654", false, now, Sample{CPU: 3})
	c.Ingest("host-1", true, now, Sample{CPU: 4})
	c.Ingest("host-2", true, now, Sample{CPU: 5})

	c.RemoveHost("host-1")

	c.mu.Lock()
	defer c.mu.Unlock()
	// host-1 and its containers must be gone at tier 0 (the only tier
	// raw samples populate).
	for _, id := range []string{"host-1", "host-1:abc123def456", "host-1:def456abc123"} {
		if _, ok := c.state[entityKey{id, 0}]; ok {
			t.Errorf("expected no state for %q, still present", id)
		}
	}
	// host-2 and its container must still be present.
	if _, ok := c.state[entityKey{"host-2:fedcba987654", 0}]; !ok {
		t.Errorf("host-2 container state was incorrectly removed")
	}
	if _, ok := c.state[entityKey{"host-2", 0}]; !ok {
		t.Errorf("host-2 host state was incorrectly removed")
	}
}

func TestCascade_RemoveHost_NoPartialMatches(t *testing.T) {
	// Verify RemoveHost("host-1") does NOT match "host-10" or "host-100".
	c, _, _ := newTestCascade(64)
	now := time.Unix(1_000_000, 0)

	c.Ingest("host-1:abc", false, now, Sample{CPU: 1})
	c.Ingest("host-10:def", false, now, Sample{CPU: 2})
	c.Ingest("host-100:ghi", false, now, Sample{CPU: 3})

	c.RemoveHost("host-1")

	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.state[entityKey{"host-1:abc", 0}]; ok {
		t.Errorf("host-1's container should have been removed")
	}
	if _, ok := c.state[entityKey{"host-10:def", 0}]; !ok {
		t.Errorf("host-10 container was incorrectly removed (prefix collision)")
	}
	if _, ok := c.state[entityKey{"host-100:ghi", 0}]; !ok {
		t.Errorf("host-100 container was incorrectly removed (prefix collision)")
	}
}

func TestCascade_RemoveHost_NoOpOnMissing(t *testing.T) {
	// Removing a host that was never ingested must be a silent no-op:
	// no panic, no mutation of unrelated entries.
	c, _, _ := newTestCascade(64)
	now := time.Unix(1_000_000, 0)

	c.Ingest("host-2:abc", false, now, Sample{CPU: 1})
	c.Ingest("host-2", true, now, Sample{CPU: 2})

	c.RemoveHost("host-does-not-exist")

	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.state[entityKey{"host-2:abc", 0}]; !ok {
		t.Errorf("host-2 container state was incorrectly removed")
	}
	if _, ok := c.state[entityKey{"host-2", 0}]; !ok {
		t.Errorf("host-2 host state was incorrectly removed")
	}
	if len(c.state) != 2 {
		t.Errorf("expected 2 state entries after no-op removal, got %d", len(c.state))
	}
}

func TestCascade_RemoveHost_EmptyCascade(t *testing.T) {
	// Removing any host from a fresh, empty cascade must not panic.
	c, _, _ := newTestCascade(64)

	c.RemoveHost("host-1")

	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.state) != 0 {
		t.Errorf("expected empty state after RemoveHost on empty cascade, got %d entries", len(c.state))
	}
}

func TestCascade_RemoveHost_ClearsAllTiers(t *testing.T) {
	// RemoveHost must drop every (entity, tier) entry for the host, not
	// just tier 0. Raw Ingest only feeds tier 0, so we populate higher
	// tiers directly via c.state (same-package access) to assert that
	// the removal loop does not accidentally filter by tierIdx.
	c, _, _ := newTestCascade(64)

	c.mu.Lock()
	for tierIdx := 0; tierIdx < 5; tierIdx++ {
		c.state[entityKey{"host-1", tierIdx}] = tierState{bucketTs: time.Unix(int64(tierIdx+1), 0), isHost: true}
		c.state[entityKey{"host-1:container", tierIdx}] = tierState{bucketTs: time.Unix(int64(tierIdx+1), 0)}
		c.state[entityKey{"host-2", tierIdx}] = tierState{bucketTs: time.Unix(int64(tierIdx+1), 0), isHost: true}
	}
	c.mu.Unlock()

	c.RemoveHost("host-1")

	c.mu.Lock()
	defer c.mu.Unlock()
	for tierIdx := 0; tierIdx < 5; tierIdx++ {
		if _, ok := c.state[entityKey{"host-1", tierIdx}]; ok {
			t.Errorf("host-1 tier %d state was not removed", tierIdx)
		}
		if _, ok := c.state[entityKey{"host-1:container", tierIdx}]; ok {
			t.Errorf("host-1:container tier %d state was not removed", tierIdx)
		}
		if _, ok := c.state[entityKey{"host-2", tierIdx}]; !ok {
			t.Errorf("host-2 tier %d state was incorrectly removed", tierIdx)
		}
	}
}
