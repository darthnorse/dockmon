package main

import (
	"sync"
	"time"
)

// ContainerStats holds real-time stats for a single container
type ContainerStats struct {
	ContainerID   string    `json:"container_id"`
	ContainerName string    `json:"container_name"`
	HostID        string    `json:"host_id"`
	CPUPercent    float64   `json:"cpu_percent"`
	MemoryUsage   uint64    `json:"memory_usage"`
	MemoryLimit   uint64    `json:"memory_limit"`
	MemoryPercent float64   `json:"memory_percent"`
	NetworkRx     uint64    `json:"network_rx"`
	NetworkTx     uint64    `json:"network_tx"`
	LastUpdate    time.Time `json:"last_update"`
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

// StatsCache is a thread-safe cache for container and host stats
type StatsCache struct {
	mu             sync.RWMutex
	containerStats map[string]*ContainerStats // key: containerID
	hostStats      map[string]*HostStats      // key: hostID
}

// NewStatsCache creates a new stats cache
func NewStatsCache() *StatsCache {
	return &StatsCache{
		containerStats: make(map[string]*ContainerStats),
		hostStats:      make(map[string]*HostStats),
	}
}

// UpdateContainerStats updates stats for a container
func (c *StatsCache) UpdateContainerStats(stats *ContainerStats) {
	c.mu.Lock()
	defer c.mu.Unlock()

	stats.LastUpdate = time.Now()
	c.containerStats[stats.ContainerID] = stats
}

// GetContainerStats retrieves stats for a specific container
func (c *StatsCache) GetContainerStats(containerID string) (*ContainerStats, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	stats, ok := c.containerStats[containerID]
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
func (c *StatsCache) RemoveContainerStats(containerID string) {
	c.mu.Lock()
	defer c.mu.Unlock()

	delete(c.containerStats, containerID)
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
