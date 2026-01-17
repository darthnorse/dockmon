package main

import (
	"context"
	"log"
	"time"

	dockerpkg "github.com/darthnorse/dockmon-shared/docker"
)

// Aggregator aggregates container stats into host-level metrics
type Aggregator struct {
	cache             *StatsCache
	streamManager     *StreamManager
	aggregateInterval time.Duration
	hostProcReader    *HostProcReader
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

	// Aggregate stats for each host that has a registered Docker client
	for hostID, containers := range hostContainers {
		// Only aggregate if the host still has a registered Docker client
		// This prevents recreating stats for hosts that were just deleted
		if a.streamManager.HasHost(hostID) {
			hostStats := a.aggregateHostStats(hostID, containers)
			a.cache.UpdateHostStats(hostStats)
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
