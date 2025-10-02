package main

import (
	"context"
	"log"
	"time"
)

// Aggregator aggregates container stats into host-level metrics
type Aggregator struct {
	cache           *StatsCache
	aggregateInterval time.Duration
}

// NewAggregator creates a new aggregator
func NewAggregator(cache *StatsCache, interval time.Duration) *Aggregator {
	return &Aggregator{
		cache:           cache,
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

	// Aggregate stats for each host
	for hostID, containers := range hostContainers {
		hostStats := a.aggregateHostStats(hostID, containers)
		a.cache.UpdateHostStats(hostStats)
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

	// Only count containers updated in the last 30 seconds
	cutoff := time.Now().Add(-30 * time.Second)

	for _, stats := range containers {
		if stats.LastUpdate.Before(cutoff) {
			continue // Skip stale stats
		}

		totalCPU += stats.CPUPercent
		totalMemUsage += stats.MemoryUsage
		totalMemLimit += stats.MemoryLimit
		totalNetRx += stats.NetworkRx
		totalNetTx += stats.NetworkTx
		validContainers++
	}

	// Calculate averages
	var avgCPU, memPercent float64

	if validContainers > 0 {
		avgCPU = totalCPU / float64(validContainers)
	}

	if totalMemLimit > 0 {
		memPercent = (float64(totalMemUsage) / float64(totalMemLimit)) * 100.0
	}

	// Round to 1 decimal place
	avgCPU = roundToDecimal(avgCPU, 1)
	memPercent = roundToDecimal(memPercent, 1)

	return &HostStats{
		HostID:           hostID,
		CPUPercent:       avgCPU,
		MemoryPercent:    memPercent,
		MemoryUsedBytes:  totalMemUsage,
		MemoryLimitBytes: totalMemLimit,
		NetworkRxBytes:   totalNetRx,
		NetworkTxBytes:   totalNetTx,
		ContainerCount:   validContainers,
	}
}

// roundToDecimal rounds a float to n decimal places
func roundToDecimal(value float64, places int) float64 {
	shift := float64(1)
	for i := 0; i < places; i++ {
		shift *= 10
	}
	return float64(int(value*shift+0.5)) / shift
}
