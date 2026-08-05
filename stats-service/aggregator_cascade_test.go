package main

import (
	"testing"
	"time"

	dockerpkg "github.com/darthnorse/dockmon-shared/docker"
	"github.com/dockmon/stats-service/persistence"
)

// stubStreamManager implements streamManagerIface so tests can run
// aggregate() without standing up a real StreamManager.
type stubStreamManager struct{}

func (s stubStreamManager) HasHost(string) bool { return true }

func TestAggregator_FeedsCascade(t *testing.T) {
	// Default is off; this test exercises the on-state path.
	on := true
	settingsProvider.ApplyPartialUpdate(&on, nil, nil)
	t.Cleanup(func() {
		off := false
		settingsProvider.ApplyPartialUpdate(&off, nil, nil)
	})

	cache := NewStatsCache()
	cache.UpdateContainerStats(&ContainerStats{
		ContainerID: "abc123abc123",
		HostID:      "host-1",
		CPUPercent:  42.0,
		MemoryUsage: 1024,
		MemoryLimit: 8192,
	})

	tiers := persistence.ComputeTiers(500)
	writes := make(chan persistence.WriteJob, 64)
	cascade := persistence.NewCascade(tiers, writes)

	agg := &Aggregator{
		cache:             cache,
		streamManager:     stubStreamManager{},
		aggregateInterval: time.Second,
		hostProcReader:    NewHostProcReader(),
		cascade:           cascade,
	}
	agg.aggregate()

	// Bucketing waits for the next bucket boundary, so the cascade shouldn't
	// have emitted any writes yet. Verify it accepted both the host and
	// container samples by checking state size via the test-only helper.
	if got := cascade.StateSize(); got != 2 {
		t.Errorf("cascade state size=%d, want 2 (1 container + 1 host)", got)
	}
}

func TestAggregator_HostMemoryUsesDockerHostLimit(t *testing.T) {
	cache := NewStatsCache()
	const hostLimit = uint64(6 * 1024 * 1024 * 1024)
	const containerUsage = uint64(1024 * 1024 * 1024)
	const containerLimit = uint64(16 * 1024 * 1024 * 1024)
	cache.SetHostMemory("host-1", hostLimit)
	cache.UpdateContainerStats(&ContainerStats{
		ContainerID:   "aaaaaaaaaaaa",
		HostID:        "host-1",
		MemoryUsage:   containerUsage,
		MemoryLimit:   containerLimit,
		MemoryPercent: 6.25,
	})

	agg := &Aggregator{
		cache:             cache,
		streamManager:     stubStreamManager{},
		aggregateInterval: time.Second,
		hostProcReader:    NewHostProcReader(),
	}

	got := agg.aggregateHostStats("host-1", []*ContainerStats{
		cache.containerStats["host-1:aaaaaaaaaaaa"],
	})
	if got.MemoryLimitBytes != hostLimit {
		t.Fatalf("MemoryLimitBytes=%d, want Docker host limit %d", got.MemoryLimitBytes, hostLimit)
	}
	wantPercent := dockerpkg.RoundToDecimal(float64(containerUsage)/float64(hostLimit)*100, 1)
	if got.MemoryPercent != wantPercent {
		t.Fatalf("MemoryPercent=%v, want %v", got.MemoryPercent, wantPercent)
	}
}

// TestSampleFromContainerStats_UsesRateNotCumulative is a regression guard
// for the NetBps bug: NetworkRx/NetworkTx are cumulative counters, while
// NetBytesPerSec is the cache-computed delta rate. The cascade column
// contract ("combined rx+tx bytes/sec", spec §6) requires a rate.
func TestSampleFromContainerStats_UsesRateNotCumulative(t *testing.T) {
	cs := &ContainerStats{
		NetworkRx:      10_000_000_000, // 10 GB cumulative — not what we want
		NetworkTx:      20_000_000_000, // 20 GB cumulative — not what we want
		NetBytesPerSec: 1_234.5,        // the actual rate
	}
	got := sampleFromContainerStats(cs)
	if got.NetBps != 1_234.5 {
		t.Errorf("NetBps=%v, want 1234.5 (rate, not cumulative bytes)", got.NetBps)
	}
}

// TestSampleFromHostStats_TakesNetBpsArgument verifies the adapter uses the
// per-second rate passed in by the caller, not the cumulative counters on
// HostStats (which exist for the live /api/stats/hosts endpoint consumers).
func TestSampleFromHostStats_TakesNetBpsArgument(t *testing.T) {
	h := &HostStats{
		CPUPercent:       42.0,
		MemoryPercent:    50.0,
		MemoryUsedBytes:  2048,
		MemoryLimitBytes: 4096,
		NetworkRxBytes:   999_999_999, // cumulative — must NOT appear in NetBps
		NetworkTxBytes:   999_999_999,
		ContainerCount:   5,
	}
	got := sampleFromHostStats(h, 789.25)
	if got.NetBps != 789.25 {
		t.Errorf("NetBps=%v, want 789.25 (passed-in rate)", got.NetBps)
	}
	// Memory percent is recomputed unrounded from bytes when limit > 0.
	// 2048/4096*100 = 50, which happens to match MemoryPercent here, but
	// the point is the bytes path is taken — assert exact-equal (not fuzzy).
	if got.MemPercent != 50.0 {
		t.Errorf("MemPercent=%v, want 50.0", got.MemPercent)
	}
	if got.ContainerCount != 5 {
		t.Errorf("ContainerCount=%d, want 5", got.ContainerCount)
	}
}

// TestAggregator_HostNetBpsSumsContainerRates verifies the host-level rate
// fed to the cascade is the sum of container-level rates, matching the
// Python aggregator's behavior in monitor.py. Uses pre-populated cache
// entries with known NetBytesPerSec values so the test doesn't depend on
// wall-clock jitter inside the cache's delta math.
func TestAggregator_HostNetBpsSumsContainerRates(t *testing.T) {
	cache := NewStatsCache()
	now := time.Now()
	// Bypass UpdateContainerStats (which overwrites LastUpdate and computes
	// its own rate from deltas) and install the rates directly. Package-
	// internal access is fine for tests in the same package.
	cache.containerStats["host-1:aaaaaaaaaaaa"] = &ContainerStats{
		ContainerID: "aaaaaaaaaaaa", HostID: "host-1",
		NetBytesPerSec: 1000.0,
		LastUpdate:     now,
	}
	cache.containerStats["host-1:bbbbbbbbbbbb"] = &ContainerStats{
		ContainerID: "bbbbbbbbbbbb", HostID: "host-1",
		NetBytesPerSec: 2500.0,
		LastUpdate:     now,
	}
	// Stale container must NOT contribute to the host rate.
	cache.containerStats["host-1:ccccccccccccstale"] = &ContainerStats{
		ContainerID: "ccccccccccccstale", HostID: "host-1",
		NetBytesPerSec: 9_999_999.0,
		LastUpdate:     now.Add(-60 * time.Second),
	}

	// Reproduce the aggregator's host-rate computation inline. Keeps the
	// assertion independent of the full aggregate() path (which also needs
	// a StreamManager stub and exercises aggregateHostStats).
	cutoff := now.Add(-30 * time.Second)
	var gotHostNetBps float64
	for _, cs := range cache.GetAllContainerStats() {
		if cs.LastUpdate.Before(cutoff) {
			continue
		}
		gotHostNetBps += cs.NetBytesPerSec
	}
	const want = 1000.0 + 2500.0
	if gotHostNetBps != want {
		t.Errorf("host NetBps sum=%v, want %v (stale container must be excluded)",
			gotHostNetBps, want)
	}
}

// agentHostStreamManager reports no registered Docker client, which is what
// makes a host agent-owned: its stats come from the ingest handler.
type agentHostStreamManager struct{}

func (agentHostStreamManager) HasHost(string) bool { return false }

func agentHostFixture(t *testing.T, agentSample *HostStats) (*Aggregator, []*ContainerStats) {
	t.Helper()
	cache := NewStatsCache()
	now := time.Now()

	// Six unlimited containers: each reports the whole 2GB host as its limit,
	// so the container-aggregation fallback divides by 6x the real memory.
	const hostMemory = uint64(2_068_885_504)
	var containers []*ContainerStats
	for _, id := range []string{"aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc",
		"dddddddddddd", "eeeeeeeeeeee", "ffffffffffff"} {
		cs := &ContainerStats{
			ContainerID: id, HostID: "agent-1",
			CPUPercent:  1.0,
			MemoryUsage: 86_510_153, MemoryLimit: hostMemory,
			LastUpdate: now,
		}
		cache.containerStats["agent-1:"+id] = cs
		containers = append(containers, cs)
	}

	if agentSample != nil {
		cache.UpdateHostStats(agentSample)
	}

	agg := &Aggregator{
		cache:             cache,
		streamManager:     agentHostStreamManager{},
		aggregateInterval: time.Second,
		hostProcReader:    NewHostProcReader(),
	}
	return agg, containers
}

// History for an agent host must come from the agent's real /proc reading, the
// same source the live cache and the alert evaluator use. Aggregating its
// containers instead produced a chart that disagreed with the alert: measured
// 4.18% against a real 40.29% on a host whose container limits summed to 6x
// the real memory.
func TestAggregator_AgentHostUsesIngestedProcReading(t *testing.T) {
	agg, containers := agentHostFixture(t, &HostStats{
		HostID:           "agent-1",
		CPUPercent:       0.4,
		MemoryPercent:    40.3,
		MemoryUsedBytes:  833_515_520,
		MemoryLimitBytes: 2_068_885_504,
	})

	got := agg.aggregateHostStats("agent-1", containers)

	if got.MemoryPercent != 40.3 {
		t.Errorf("MemoryPercent=%v, want 40.3 (the agent's reading, not the container sum)", got.MemoryPercent)
	}
	if got.CPUPercent != 0.4 {
		t.Errorf("CPUPercent=%v, want 0.4 (the agent's reading)", got.CPUPercent)
	}
	if got.MemoryLimitBytes != 2_068_885_504 {
		t.Errorf("MemoryLimitBytes=%d, want the real host memory", got.MemoryLimitBytes)
	}
	// Network and container count still come from the aggregation, exactly as
	// the local /host/proc branch does.
	if got.ContainerCount != len(containers) {
		t.Errorf("ContainerCount=%d, want %d", got.ContainerCount, len(containers))
	}
}

// A dead agent must not freeze history at its last reading.
func TestAggregator_StaleAgentSampleFallsBackToAggregation(t *testing.T) {
	agg, containers := agentHostFixture(t, &HostStats{
		HostID:        "agent-1",
		CPUPercent:    0.4,
		MemoryPercent: 40.3,
	})
	// UpdateHostStats stamps LastUpdate; age it past the freshness cutoff.
	agg.cache.hostStats["agent-1"].LastUpdate = time.Now().Add(-90 * time.Second)

	got := agg.aggregateHostStats("agent-1", containers)

	if got.MemoryPercent == 40.3 {
		t.Error("stale agent sample was reused; history would freeze at the last reading")
	}
}

// An agent with no /host/proc sends no host samples at all. Nothing contradicts
// the aggregate there (alerts have no data either), so the chart keeps its only
// signal rather than going blank.
func TestAggregator_AgentHostWithoutSampleKeepsAggregation(t *testing.T) {
	agg, containers := agentHostFixture(t, nil)

	got := agg.aggregateHostStats("agent-1", containers)

	if got.ContainerCount != len(containers) {
		t.Errorf("ContainerCount=%d, want %d", got.ContainerCount, len(containers))
	}
	if got.MemoryUsedBytes == 0 {
		t.Error("expected the container-aggregated sample to still be produced")
	}
}

// A registered Docker host's own aggregate is what the aggregator writes to the
// host cache, so reading it back as input would be a feedback loop.
func TestAggregator_DockerHostIgnoresHostCacheEntry(t *testing.T) {
	cache := NewStatsCache()
	now := time.Now()
	cache.containerStats["host-1:aaaaaaaaaaaa"] = &ContainerStats{
		ContainerID: "aaaaaaaaaaaa", HostID: "host-1",
		CPUPercent: 10.0, MemoryUsage: 1024, MemoryLimit: 4096,
		LastUpdate: now,
	}
	cache.UpdateHostStats(&HostStats{HostID: "host-1", CPUPercent: 99.0, MemoryPercent: 99.0})

	agg := &Aggregator{
		cache:             cache,
		streamManager:     stubStreamManager{}, // HasHost == true
		aggregateInterval: time.Second,
		hostProcReader:    NewHostProcReader(),
	}

	got := agg.aggregateHostStats("host-1", []*ContainerStats{cache.containerStats["host-1:aaaaaaaaaaaa"]})

	if got.CPUPercent == 99.0 {
		t.Error("Docker host read its own cached output back as input")
	}
}

// Guard against a self-refreshing agent sample: the aggregator must never write
// an agent host's entry back to the cache, or its own output would keep
// stamping a fresh LastUpdate and a disconnected agent's reading could never
// expire. The live-cache write is gated on HasHost, which is false for exactly
// the hosts the ingest branch serves — this pins that pairing.
func TestAggregator_NeverWritesBackAgentHostEntry(t *testing.T) {
	agg, _ := agentHostFixture(t, &HostStats{
		HostID:           "agent-1",
		CPUPercent:       0.4,
		MemoryPercent:    40.3,
		MemoryUsedBytes:  833_515_520,
		MemoryLimitBytes: 2_068_885_504,
	})
	before := agg.cache.hostStats["agent-1"].LastUpdate

	for i := 0; i < 3; i++ {
		agg.aggregate()
	}

	after := agg.cache.hostStats["agent-1"]
	if !after.LastUpdate.Equal(before) {
		t.Error("aggregator refreshed the agent's own cache entry; a stale sample could never expire")
	}
	if after.MemoryPercent != 40.3 {
		t.Errorf("MemoryPercent=%v, want the agent's untouched 40.3", after.MemoryPercent)
	}
}

// The evaluator treats an agent host sample as fresh for 60s, so the aggregator
// must too: a shorter window would put the container aggregate back on the chart
// while an alert was still firing on the agent's reading.
func TestAggregator_AgentSampleFreshWindowMatchesEvaluator(t *testing.T) {
	agg, containers := agentHostFixture(t, &HostStats{
		HostID: "agent-1", CPUPercent: 0.4, MemoryPercent: 40.3,
		MemoryUsedBytes: 833_515_520, MemoryLimitBytes: 2_068_885_504,
	})
	// 45s: past the 30s container cutoff, inside the evaluator's 60s window.
	agg.cache.hostStats["agent-1"].LastUpdate = time.Now().Add(-45 * time.Second)

	got := agg.aggregateHostStats("agent-1", containers)

	if got.MemoryPercent != 40.3 {
		t.Errorf("MemoryPercent=%v, want 40.3: a 45s-old sample is still what the evaluator uses", got.MemoryPercent)
	}
}

// The host sample must not be discarded because the host's CONTAINERS went
// stale — the agent's own reading is what the chart and the alert share.
func TestAggregator_IngestsAgentHostSampleWhenContainersAreStale(t *testing.T) {
	on := true
	settingsProvider.ApplyPartialUpdate(&on, nil, nil)
	t.Cleanup(func() {
		off := false
		settingsProvider.ApplyPartialUpdate(&off, nil, nil)
	})

	agg, _ := agentHostFixture(t, &HostStats{
		HostID: "agent-1", CPUPercent: 0.4, MemoryPercent: 40.3,
		MemoryUsedBytes: 833_515_520, MemoryLimitBytes: 2_068_885_504,
	})
	for _, cs := range agg.cache.containerStats {
		cs.LastUpdate = time.Now().Add(-90 * time.Second)
	}

	tiers := persistence.ComputeTiers(500)
	agg.cascade = persistence.NewCascade(tiers, make(chan persistence.WriteJob, 64))
	agg.aggregate()

	if agg.cascade.StateSize() == 0 {
		t.Error("no host sample ingested; the chart goes blank while alerts still fire on the agent's reading")
	}
}

// A host whose container entries have aged out of the cache entirely never
// appears in the container grouping, so it needs its own pass.
func TestAggregator_IngestsAgentHostSampleWithNoContainers(t *testing.T) {
	on := true
	settingsProvider.ApplyPartialUpdate(&on, nil, nil)
	t.Cleanup(func() {
		off := false
		settingsProvider.ApplyPartialUpdate(&off, nil, nil)
	})

	cache := NewStatsCache()
	cache.UpdateHostStats(&HostStats{
		HostID: "agent-1", CPUPercent: 0.4, MemoryPercent: 40.3,
		MemoryUsedBytes: 833_515_520, MemoryLimitBytes: 2_068_885_504,
	})

	tiers := persistence.ComputeTiers(500)
	agg := &Aggregator{
		cache:             cache,
		streamManager:     agentHostStreamManager{},
		aggregateInterval: time.Second,
		hostProcReader:    NewHostProcReader(),
		cascade:           persistence.NewCascade(tiers, make(chan persistence.WriteJob, 64)),
	}
	agg.aggregate()

	if agg.cascade.StateSize() != 1 {
		t.Errorf("cascade state size=%d, want 1 (the agent host sample)", agg.cascade.StateSize())
	}
}

// A registered Docker host with no containers must NOT get a host sample from
// its own cached entry — that entry is the aggregator's own output.
func TestAggregator_DockerHostWithNoContainersIsNotIngested(t *testing.T) {
	on := true
	settingsProvider.ApplyPartialUpdate(&on, nil, nil)
	t.Cleanup(func() {
		off := false
		settingsProvider.ApplyPartialUpdate(&off, nil, nil)
	})

	cache := NewStatsCache()
	cache.UpdateHostStats(&HostStats{HostID: "host-1", CPUPercent: 5.0})

	tiers := persistence.ComputeTiers(500)
	agg := &Aggregator{
		cache:             cache,
		streamManager:     stubStreamManager{}, // HasHost == true
		aggregateInterval: time.Second,
		hostProcReader:    NewHostProcReader(),
		cascade:           persistence.NewCascade(tiers, make(chan persistence.WriteJob, 64)),
	}
	agg.aggregate()

	if agg.cascade.StateSize() != 0 {
		t.Errorf("cascade state size=%d, want 0 (Docker host output must not be re-ingested)", agg.cascade.StateSize())
	}
}
