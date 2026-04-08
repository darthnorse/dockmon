package main

import (
	"testing"
	"time"

	"github.com/dockmon/stats-service/persistence"
)

// stubStreamManager implements streamManagerIface so tests can run
// aggregate() without standing up a real StreamManager.
type stubStreamManager struct{}

func (s stubStreamManager) HasHost(string) bool { return true }

func TestAggregator_FeedsCascade(t *testing.T) {
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
