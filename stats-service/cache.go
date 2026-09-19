package main

import (
	"sync"
	"time"

	"github.com/darthnorse/dockmon-shared/hostdisk"
)

// ContainerStats holds real-time stats for a single container
type ContainerStats struct {
	ContainerID      string    `json:"container_id"`
	ContainerName    string    `json:"container_name"`
	HostID           string    `json:"host_id"`
	CPUPercent       float64   `json:"cpu_percent"`
	MemoryUsage      uint64    `json:"memory_usage"`
	MemoryLimit      uint64    `json:"memory_limit"`
	MemoryPercent    float64   `json:"memory_percent"`
	NetworkRx        uint64    `json:"network_rx"`
	NetworkTx        uint64    `json:"network_tx"`
	NetBytesPerSec   float64   `json:"net_bytes_per_sec"` // Calculated network rate
	NetRxBytesPerSec float64   `json:"net_rx_bytes_per_sec"`
	NetTxBytesPerSec float64   `json:"net_tx_bytes_per_sec"`
	DiskRead         uint64    `json:"disk_read"`
	DiskWrite        uint64    `json:"disk_write"`
	LastUpdate       time.Time `json:"last_update"`
}

// HostStats holds aggregated stats for a host
type HostStats struct {
	HostID           string    `json:"host_id"`
	CPUPercent       float64   `json:"cpu_percent"`
	MemoryPercent    float64   `json:"memory_percent"`
	MemoryUsedBytes  uint64    `json:"memory_used_bytes"`
	MemoryLimitBytes uint64    `json:"memory_limit_bytes"`
	NetworkRxBytes   uint64    `json:"network_rx_bytes"`
	NetworkTxBytes   uint64    `json:"network_tx_bytes"`
	ContainerCount   int       `json:"container_count"`
	LastUpdate       time.Time `json:"last_update"`

	// Nil serializes to no disk keys at all, so the evaluator sees the metric
	// as absent rather than as 0% used.
	*hostdisk.HostDisk
}

// networkBaseline tracks previous network values for rate calculation
type networkBaseline struct {
	totalBytes uint64 // rx + tx total
	rxBytes    uint64
	txBytes    uint64
	timestamp  time.Time // when this measurement was taken
}

// StatsCache is a thread-safe cache for container and host stats
type StatsCache struct {
	mu             sync.RWMutex
	containerStats map[string]*ContainerStats  // key: composite key (hostID:containerID)
	hostStats      map[string]*HostStats       // key: hostID
	lastNetStats   map[string]*networkBaseline // key: composite key (hostID:containerID)
	hostNumCPUs    map[string]int              // key: hostID -> number of CPUs on host
	hostMemory     map[string]uint64           // key: hostID -> total memory available to Docker
	localHosts     map[string]bool             // key: hostID -> true if local host
}

// NewStatsCache creates a new stats cache
func NewStatsCache() *StatsCache {
	return &StatsCache{
		containerStats: make(map[string]*ContainerStats),
		hostStats:      make(map[string]*HostStats),
		lastNetStats:   make(map[string]*networkBaseline),
		hostNumCPUs:    make(map[string]int),
		hostMemory:     make(map[string]uint64),
		localHosts:     make(map[string]bool),
	}
}

// SetHostNumCPUs stores the number of CPUs for a host
func (c *StatsCache) SetHostNumCPUs(hostID string, numCPUs int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.hostNumCPUs[hostID] = numCPUs
}

// GetHostNumCPUs retrieves the number of CPUs for a host (returns 1 if not set)
func (c *StatsCache) GetHostNumCPUs(hostID string) int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	if numCPUs, ok := c.hostNumCPUs[hostID]; ok && numCPUs > 0 {
		return numCPUs
	}
	return 1 // Default to 1 to avoid division by zero
}

// SetHostMemory stores the total memory available to Docker for a host.
func (c *StatsCache) SetHostMemory(hostID string, totalMemory uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.hostMemory[hostID] = totalMemory
}

// GetHostMemory retrieves the total memory available to Docker for a host.
func (c *StatsCache) GetHostMemory(hostID string) uint64 {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.hostMemory[hostID]
}

// SetHostLocal marks a host as local (for /host/proc reading)
func (c *StatsCache) SetHostLocal(hostID string, isLocal bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.localHosts[hostID] = isLocal
}

// IsHostLocal returns true if the host is marked as local
func (c *StatsCache) IsHostLocal(hostID string) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.localHosts[hostID]
}

// UpdateContainerStats updates stats for a container and calculates network rate
func (c *StatsCache) UpdateContainerStats(stats *ContainerStats) {
	c.mu.Lock()
	defer c.mu.Unlock()

	now := time.Now()
	stats.LastUpdate = now

	// Use composite key to support containers with duplicate IDs on different hosts
	compositeKey := stats.HostID + ":" + stats.ContainerID

	// Calculate network rates (bytes per second) from the cumulative counters
	if baseline, exists := c.lastNetStats[compositeKey]; exists {
		deltaTime := now.Sub(baseline.timestamp).Seconds()
		switch {
		case deltaTime <= 0:
			// No time elapsed, keep previous rates if available
			if prevStats, ok := c.containerStats[compositeKey]; ok {
				stats.NetBytesPerSec = prevStats.NetBytesPerSec
				stats.NetRxBytesPerSec = prevStats.NetRxBytesPerSec
				stats.NetTxBytesPerSec = prevStats.NetTxBytesPerSec
			}
		case stats.NetworkRx < baseline.rxBytes || stats.NetworkTx < baseline.txBytes:
			// A counter went backwards (container restart): rates stay 0 for this sample
		default:
			rx := float64(stats.NetworkRx-baseline.rxBytes) / deltaTime
			tx := float64(stats.NetworkTx-baseline.txBytes) / deltaTime
			// Sanity check: cap at 10 GB/s per container; an outlier drops all three rates
			if rx+tx <= float64(10*1024*1024*1024) {
				stats.NetRxBytesPerSec, stats.NetTxBytesPerSec, stats.NetBytesPerSec = rx, tx, rx+tx
			}
		}
	}

	// Update baseline for next calculation
	c.lastNetStats[compositeKey] = &networkBaseline{
		rxBytes:   stats.NetworkRx,
		txBytes:   stats.NetworkTx,
		timestamp: now,
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

	// Remove host num_cpus
	delete(c.hostNumCPUs, hostID)

	// Remove host memory
	delete(c.hostMemory, hostID)

	// Remove local host flag
	delete(c.localHosts, hostID)

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

	// Clean container stats and corresponding network baselines
	for id, stats := range c.containerStats {
		if now.Sub(stats.LastUpdate) > maxAge {
			delete(c.containerStats, id)
			delete(c.lastNetStats, id) // Clean up network baseline to prevent memory leak
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
