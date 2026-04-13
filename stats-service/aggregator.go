package main

import (
	"context"
	"log"
	"time"

	dockerpkg "github.com/darthnorse/dockmon-shared/docker"
	"github.com/dockmon/stats-service/persistence"
)

// streamManagerIface is the subset of *StreamManager that Aggregator needs.
// Defined as an interface so tests can fake it without standing up a real
// StreamManager (which requires Docker clients).
type streamManagerIface interface {
	HasHost(hostID string) bool
}

// Aggregator aggregates container stats into host-level metrics
type Aggregator struct {
	cache             *StatsCache
	streamManager     streamManagerIface
	aggregateInterval time.Duration
	hostProcReader    *HostProcReader
	cascade           *persistence.Cascade // optional; nil disables persistence ingest
}

// NewAggregator creates a new aggregator
func NewAggregator(cache *StatsCache, streamManager *StreamManager, interval time.Duration) *Aggregator {
	hostProcReader := NewHostProcReader()
	if hostProcReader.IsAvailable() {
		log.Println("Host /proc mounted at /host/proc - using actual host CPU/memory stats for local host")
	}

	return &Aggregator{
		cache:             cache,
		streamManager:     streamManager,
		aggregateInterval: interval,
		hostProcReader:    hostProcReader,
	}
}

// SetCascade enables persistence ingest. Pass nil to disable.
//
// Startup-ordering contract: callers MUST invoke SetCascade BEFORE
// Start(ctx) is called in its own goroutine. a.cascade is read from the
// aggregation goroutine without a mutex; wiring it in after Start has
// spawned would race. main() enforces this by construction.
func (a *Aggregator) SetCascade(c *persistence.Cascade) {
	a.cascade = c
}

// Start begins the aggregation loop
func (a *Aggregator) Start(ctx context.Context) {
	ticker := time.NewTicker(a.aggregateInterval)
	defer ticker.Stop()

	log.Printf("Aggregator started (interval: %v)", a.aggregateInterval)

	// Run once immediately
	a.aggregate()

	for {
		select {
		case <-ctx.Done():
			log.Println("Aggregator stopped")
			return
		case <-ticker.C:
			a.aggregate()
		}
	}
}

// aggregate calculates host-level stats from container stats
func (a *Aggregator) aggregate() {
	containerStats := a.cache.GetAllContainerStats()

	// Group containers by host
	hostContainers := make(map[string][]*ContainerStats)
	for _, stats := range containerStats {
		hostContainers[stats.HostID] = append(hostContainers[stats.HostID], stats)
	}

	for hostID, containers := range hostContainers {
		hostStats := a.aggregateHostStats(hostID, containers)

		// Push to live dashboard cache only for hosts with a registered
		// Docker client. Agent-managed hosts update the cache directly
		// via the ingest WebSocket handler.
		if a.streamManager.HasHost(hostID) {
			a.cache.UpdateHostStats(hostStats)
		}

		// Cascade ingest runs for ALL hosts (including agent-managed ones
		// that don't register Docker clients). The 30-second freshness
		// cutoff skips stale containers; cache.RemoveHost cleans up
		// deleted hosts.
		if a.cascade != nil && settingsProvider.PersistEnabled() {
			now := time.Now()
			cutoff := now.Add(-30 * time.Second)

			var hostNetBps float64
			var freshCount int
			for _, cs := range containers {
				if cs.LastUpdate.Before(cutoff) {
					continue
				}
				hostNetBps += cs.NetBytesPerSec
				freshCount++
			}

			// Only ingest host sample when there is fresh data. An
			// all-stale host would produce an all-zeros sample that
			// corrupts blended cascade tiers instead of leaving gaps.
			if freshCount > 0 {
				a.cascade.Ingest(hostID, true, now, sampleFromHostStats(hostStats, hostNetBps))
			}
			for _, cs := range containers {
				if cs.LastUpdate.Before(cutoff) {
					continue
				}
				compositeID := cs.HostID + ":" + cs.ContainerID
				a.cascade.Ingest(compositeID, false, now, sampleFromContainerStats(cs))
			}
		}
	}
}

// aggregateHostStats aggregates stats for a single host
func (a *Aggregator) aggregateHostStats(hostID string, containers []*ContainerStats) *HostStats {
	var (
		totalNetRx      uint64
		totalNetTx      uint64
		validContainers int
	)

	const maxUint64 = ^uint64(0)

	// Only count containers updated in the last 30 seconds
	cutoff := time.Now().Add(-30 * time.Second)

	// Always aggregate container stats for network and container count
	for _, stats := range containers {
		if stats.LastUpdate.Before(cutoff) {
			continue // Skip stale stats
		}

		// Check for overflow before adding network bytes
		if maxUint64-totalNetRx < stats.NetworkRx {
			log.Printf("Warning: Network RX overflow prevented for host %s", truncateID(hostID, 8))
			totalNetRx = maxUint64 // Cap at max instead of wrapping
		} else {
			totalNetRx += stats.NetworkRx
		}

		if maxUint64-totalNetTx < stats.NetworkTx {
			log.Printf("Warning: Network TX overflow prevented for host %s", truncateID(hostID, 8))
			totalNetTx = maxUint64
		} else {
			totalNetTx += stats.NetworkTx
		}

		validContainers++
	}

	// Check if we can use actual host stats from /host/proc (Issue #129)
	// This provides accurate CPU/memory when /proc is mounted as /host/proc:ro
	if a.cache.IsHostLocal(hostID) && a.hostProcReader.IsAvailable() {
		hostProcStats, err := a.hostProcReader.GetStats()
		if err == nil && hostProcStats != nil {
			cpuPercent := dockerpkg.RoundToDecimal(hostProcStats.CPUPercent, 1)
			memPercent := dockerpkg.RoundToDecimal(hostProcStats.MemoryPercent, 1)

			return &HostStats{
				HostID:           hostID,
				CPUPercent:       cpuPercent,
				MemoryPercent:    memPercent,
				MemoryUsedBytes:  hostProcStats.MemoryUsedBytes,
				MemoryLimitBytes: hostProcStats.MemoryTotalBytes,
				NetworkRxBytes:   totalNetRx,
				NetworkTxBytes:   totalNetTx,
				ContainerCount:   validContainers,
			}
		}
		// Fall through to container aggregation if /host/proc read failed
	}

	// Fallback: Aggregate CPU/memory from container stats
	if len(containers) == 0 {
		return &HostStats{
			HostID:         hostID,
			ContainerCount: 0,
		}
	}

	var (
		totalCPU      float64
		totalMemUsage uint64
		totalMemLimit uint64
	)

	for _, stats := range containers {
		if stats.LastUpdate.Before(cutoff) {
			continue
		}
		totalCPU += stats.CPUPercent
		totalMemUsage += stats.MemoryUsage
		totalMemLimit += stats.MemoryLimit
	}

	// Calculate totals and percentages
	var cpuPercent, memPercent float64

	// CPU: Docker reports container CPU as percentage of ALL cores combined.
	// For example, a container using 100% of one core on a 4-core system reports ~100%.
	// To get accurate host CPU, we sum all container CPU and divide by number of CPUs.
	// This gives us the percentage of total host CPU capacity being used.
	numCPUs := a.cache.GetHostNumCPUs(hostID)
	if numCPUs > 0 {
		cpuPercent = totalCPU / float64(numCPUs)
	} else {
		cpuPercent = totalCPU // Fallback if numCPUs not set
	}

	if totalMemLimit > 0 {
		memPercent = (float64(totalMemUsage) / float64(totalMemLimit)) * 100.0
	}

	// Round to 1 decimal place - using shared package
	cpuPercent = dockerpkg.RoundToDecimal(cpuPercent, 1)
	memPercent = dockerpkg.RoundToDecimal(memPercent, 1)

	return &HostStats{
		HostID:           hostID,
		CPUPercent:       cpuPercent,
		MemoryPercent:    memPercent,
		MemoryUsedBytes:  totalMemUsage,
		MemoryLimitBytes: totalMemLimit,
		NetworkRxBytes:   totalNetRx,
		NetworkTxBytes:   totalNetTx,
		ContainerCount:   validContainers,
	}
}

// sampleFromHostStats builds a persistence.Sample from aggregated HostStats.
// HostStats.NetworkRxBytes/NetworkTxBytes are cumulative byte counters, not
// rates, so the caller must compute the per-second rate (summed from each
// container's cache-computed NetBytesPerSec) and pass it as netBps. See the
// "combined rx+tx bytes/sec" column contract in spec §6.
func sampleFromHostStats(h *HostStats, netBps float64) persistence.Sample {
	// Recompute memory percent from bytes when a limit is known: both the
	// /host/proc and container-aggregation paths in aggregateHostStats round
	// MemoryPercent to 1 decimal for display. Historical persistence wants
	// the unrounded value for more accurate blending, and the raw bytes are
	// always set alongside the rounded percent. Fall back to the stored
	// percentage only if MemoryLimitBytes is unknown.
	var memPct float64
	if h.MemoryLimitBytes > 0 {
		memPct = float64(h.MemoryUsedBytes) / float64(h.MemoryLimitBytes) * 100
	} else {
		memPct = h.MemoryPercent
	}
	return persistence.Sample{
		CPU:            h.CPUPercent,
		MemPercent:     memPct,
		MemUsed:        h.MemoryUsedBytes,
		MemLimit:       h.MemoryLimitBytes,
		NetBps:         netBps,
		ContainerCount: h.ContainerCount,
	}
}

// sampleFromContainerStats builds a persistence.Sample from ContainerStats.
// NetBytesPerSec is already a delta rate computed by StatsCache on each
// UpdateContainerStats call (cache.go), including counter-reset handling
// and outlier capping — reusing it avoids duplicating that logic here.
func sampleFromContainerStats(cs *ContainerStats) persistence.Sample {
	return persistence.Sample{
		CPU:        cs.CPUPercent,
		MemPercent: cs.MemoryPercent,
		MemUsed:    cs.MemoryUsage,
		MemLimit:   cs.MemoryLimit,
		NetBps:     cs.NetBytesPerSec,
	}
}
