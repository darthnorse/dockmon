package main

import (
	"sync"
	"time"
)

// ContainerStats holds real-time stats for a single container
type ContainerStats struct {
	ContainerID     string    `json:"container_id"`
	ContainerName   string    `json:"container_name"`
	HostID          string    `json:"host_id"`
	CPUPercent      float64   `json:"cpu_percent"`
	MemoryUsage     uint64    `json:"memory_usage"`
	MemoryLimit     uint64    `json:"memory_limit"`
	MemoryPercent   float64   `json:"memory_percent"`
	NetworkRx       uint64    `json:"network_rx"`
	NetworkTx       uint64    `json:"network_tx"`
	NetBytesPerSec  float64   `json:"net_bytes_per_sec"`  // Calculated network rate
	DiskRead        uint64    `json:"disk_read"`
	DiskWrite       uint64    `json:"disk_write"`
	LastUpdate      time.Time `json:"last_update"`
}

// HostStats holds aggregated stats for a host
type HostStats struct {
	HostID            string    `json:"host_id"`
	CPUPercent        float64   `json:"cpu_percent"`
	MemoryPercent     float64   `json:"memory_percent"`
	MemoryUsedBytes   uint64    `json:"memory_used_bytes"`
	MemoryLimitBytes  uint64    `json:"memory_limit_bytes"`
	NetworkRxBytes    uint64    `json:"network_rx_bytes"`
	NetworkTxBytes    uint64    `json:"network_tx_bytes"`
	ContainerCount    int       `json:"container_count"`
	LastUpdate        time.Time `json:"last_update"`
}

// networkBaseline tracks previous network values for rate calculation
type networkBaseline struct {
	totalBytes uint64    // rx + tx total
	timestamp  time.Time // when this measurement was taken
}

// StatsCache is a thread-safe cache for container and host stats
type StatsCache struct {
	mu             sync.RWMutex
	containerStats map[string]*ContainerStats     // key: composite key (hostID:containerID)
	hostStats      map[string]*HostStats          // key: hostID
	lastNetStats   map[string]*networkBaseline    // key: composite key (hostID:containerID)
}

// NewStatsCache creates a new stats cache
func NewStatsCache() *StatsCache {
	return &StatsCache{
		containerStats: make(map[string]*ContainerStats),
		hostStats:      make(map[string]*HostStats),
		lastNetStats:   make(map[string]*networkBaseline),
	}
}

// UpdateContainerStats updates stats for a container and calculates network rate
func (c *StatsCache) UpdateContainerStats(stats *ContainerStats) {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := time.Now()
	stats.LastUpdate = now

	// Use composite key to support containers with duplicate IDs on different hosts
	compositeKey := stats.HostID + ":" + stats.ContainerID

	// Calculate network rate (bytes per second)
	currentTotal := stats.NetworkRx + stats.NetworkTx

	if baseline, exists := c.lastNetStats[compositeKey]; exists {
		// Calculate delta
		deltaBytes := int64(currentTotal) - int64(baseline.totalBytes)
		deltaTime := now.Sub(baseline.timestamp).Seconds()

		if deltaTime > 0 {
			if deltaBytes < 0 {
				// Counter reset detected (container restart)
				stats.NetBytesPerSec = 0
			} else {
				// Normal case: calculate rate
				rate := float64(deltaBytes) / deltaTime

				// Sanity check: Cap at 10 Gbps per container (reasonable max)
				maxRate := float64(10 * 1024 * 1024 * 1024) // 10 GB/s
				if rate > maxRate {
					// Outlier detected, drop it
					stats.NetBytesPerSec = 0
				} else {
					stats.NetBytesPerSec = rate
				}
			}
		} else {
			// No time elapsed, keep previous rate if available
			if prevStats, ok := c.containerStats[compositeKey]; ok {
				stats.NetBytesPerSec = prevStats.NetBytesPerSec
			} else {
				stats.NetBytesPerSec = 0
			}
		}
	} else {
		// First measurement - no rate yet
		stats.NetBytesPerSec = 0
	}

	// Update baseline for next calculation
	c.lastNetStats[compositeKey] = &networkBaseline{
		totalBytes: currentTotal,
		timestamp:  now,
	}

	// Store updated stats
	c.containerStats[compositeKey] = stats
}

// GetContainerStats retrieves stats for a specific container
func (c *StatsCache) GetContainerStats(containerID, hostID string) (*ContainerStats, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	compositeKey := hostID + ":" + containerID
	stats, ok := c.containerStats[compositeKey]
	return stats, ok
}

// GetAllContainerStats returns all container stats
func (c *StatsCache) GetAllContainerStats() map[string]*ContainerStats {
	c.mu.RLock()
	defer c.mu.RUnlock()

	// Return a copy to avoid race conditions
	result := make(map[string]*ContainerStats, len(c.containerStats))
	for k, v := range c.containerStats {
		statsCopy := *v
		result[k] = &statsCopy
	}
	return result
}

// RemoveContainerStats removes stats for a container (when it stops)
func (c *StatsCache) RemoveContainerStats(containerID, hostID string) {
	c.mu.Lock()
	defer c.mu.Unlock()

	compositeKey := hostID + ":" + containerID
	delete(c.containerStats, compositeKey)
	delete(c.lastNetStats, compositeKey)
}

// UpdateHostStats updates aggregated stats for a host
func (c *StatsCache) UpdateHostStats(stats *HostStats) {
	c.mu.Lock()
	defer c.mu.Unlock()

	stats.LastUpdate = time.Now()
	c.hostStats[stats.HostID] = stats
}

// GetHostStats retrieves stats for a specific host
func (c *StatsCache) GetHostStats(hostID string) (*HostStats, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	stats, ok := c.hostStats[hostID]
	return stats, ok
}

// GetAllHostStats returns all host stats
func (c *StatsCache) GetAllHostStats() map[string]*HostStats {
	c.mu.RLock()
	defer c.mu.RUnlock()

	// Return a copy to avoid race conditions
	result := make(map[string]*HostStats, len(c.hostStats))
	for k, v := range c.hostStats {
		statsCopy := *v
		result[k] = &statsCopy
	}
	return result
}

// RemoveHostStats removes all stats for a specific host
func (c *StatsCache) RemoveHostStats(hostID string) {
	c.mu.Lock()
	defer c.mu.Unlock()

	// Remove host stats
	delete(c.hostStats, hostID)

	// Remove all container stats and network baselines for this host
	for id, stats := range c.containerStats {
		if stats.HostID == hostID {
			delete(c.containerStats, id)
			delete(c.lastNetStats, id)
		}
	}
}

// CleanStaleStats removes stats older than maxAge
func (c *StatsCache) CleanStaleStats(maxAge time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := time.Now()

	// Clean container stats
	for id, stats := range c.containerStats {
		if now.Sub(stats.LastUpdate) > maxAge {
			delete(c.containerStats, id)
		}
	}

	// Clean host stats
	for id, stats := range c.hostStats {
		if now.Sub(stats.LastUpdate) > maxAge {
			delete(c.hostStats, id)
		}
	}
}

// GetStats returns a summary of cache state
func (c *StatsCache) GetStats() (containerCount, hostCount int) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	return len(c.containerStats), len(c.hostStats)
}
