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
}

// NewAggregator creates a new aggregator
func NewAggregator(cache *StatsCache, streamManager *StreamManager, interval time.Duration) *Aggregator {
	return &Aggregator{
		cache:             cache,
		streamManager:     streamManager,
		aggregateInterval: interval,
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
	if len(containers) == 0 {
		return &HostStats{
			HostID:         hostID,
			ContainerCount: 0,
		}
	}

	var (
		totalCPU         float64
		totalMemUsage    uint64
		totalMemLimit    uint64
		totalNetRx       uint64
		totalNetTx       uint64
		validContainers  int
	)

	const maxUint64 = ^uint64(0)

	// Only count containers updated in the last 30 seconds
	cutoff := time.Now().Add(-30 * time.Second)

	for _, stats := range containers {
		if stats.LastUpdate.Before(cutoff) {
			continue // Skip stale stats
		}

		totalCPU += stats.CPUPercent
		totalMemUsage += stats.MemoryUsage
		totalMemLimit += stats.MemoryLimit

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

	// Calculate totals and percentages
	var cpuPercent, memPercent float64

	// CPU is sum of all container CPU percentages (represents total host CPU usage)
	cpuPercent = totalCPU

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
