package docker

import (
	"github.com/docker/docker/api/types"
)

// StatsResult contains calculated container statistics
type StatsResult struct {
	CPUPercent    float64
	MemoryUsage   uint64  // Working set memory (excludes reclaimable cache)
	MemoryLimit   uint64
	MemoryPercent float64
	NetworkRx     uint64
	NetworkTx     uint64
	DiskRead      uint64
	DiskWrite     uint64
}

// CalculateStats processes raw Docker stats and returns calculated metrics
// This is the proven, battle-tested logic from stats-service
func CalculateStats(stat *types.StatsJSON) *StatsResult {
	result := &StatsResult{}

	// Calculate CPU percentage
	result.CPUPercent = calculateCPUPercent(stat)

	// Calculate memory stats - working set (excludes reclaimable cache)
	// This matches what Kubernetes, cAdvisor, and Proxmox report
	result.MemoryUsage = calculateWorkingSetMemory(stat)
	result.MemoryLimit = stat.MemoryStats.Limit

	if result.MemoryLimit > 0 {
		result.MemoryPercent = (float64(result.MemoryUsage) / float64(result.MemoryLimit)) * 100.0
	}

	// Network stats - sum across all interfaces
	for _, net := range stat.Networks {
		result.NetworkRx += net.RxBytes
		result.NetworkTx += net.TxBytes
	}

	// Disk I/O stats
	for _, bio := range stat.BlkioStats.IoServiceBytesRecursive {
		if bio.Op == "Read" {
			result.DiskRead += bio.Value
		} else if bio.Op == "Write" {
			result.DiskWrite += bio.Value
		}
	}

	return result
}

// calculateCPUPercent calculates CPU percentage from Docker stats
// Algorithm matches `docker stats` command
func calculateCPUPercent(stat *types.StatsJSON) float64 {
	cpuDelta := float64(stat.CPUStats.CPUUsage.TotalUsage) - float64(stat.PreCPUStats.CPUUsage.TotalUsage)
	systemDelta := float64(stat.CPUStats.SystemUsage) - float64(stat.PreCPUStats.SystemUsage)

	if systemDelta > 0.0 && cpuDelta > 0.0 {
		numCPUs := float64(len(stat.CPUStats.CPUUsage.PercpuUsage))
		if numCPUs == 0 {
			numCPUs = 1.0
		}
		return (cpuDelta / systemDelta) * numCPUs * 100.0
	}
	return 0.0
}

// calculateWorkingSetMemory calculates working set memory (actual usage excluding reclaimable cache)
// Supports both cgroups v1 and v2
//
// Working set memory represents the actual memory pressure on the container:
// - Includes anonymous memory (process heap, stack)
// - Includes active file cache (recently accessed files)
// - Excludes inactive file cache (reclaimable without I/O)
//
// This matches the behavior of:
// - Kubernetes (kubelet memory.working_set)
// - cAdvisor (working_set metric)
// - Proxmox (used memory)
func calculateWorkingSetMemory(stat *types.StatsJSON) uint64 {
	memUsage := stat.MemoryStats.Usage
	workingSet := memUsage

	if stat.MemoryStats.Stats != nil {
		// Try cgroups v2 approach first: anon (process memory) + active_file (actively-used cache)
		// This is the most accurate method
		if anon, hasAnon := stat.MemoryStats.Stats["anon"]; hasAnon {
			if activeFile, hasActiveFile := stat.MemoryStats.Stats["active_file"]; hasActiveFile {
				// Use anon + active_file for most accurate working set
				workingSet = anon + activeFile
			} else {
				// Only anon available, use that (safest)
				workingSet = anon
			}
		} else if inactiveFile, ok := stat.MemoryStats.Stats["inactive_file"]; ok {
			// Fallback to cgroups v1 approach: subtract inactive_file
			// inactive_file is reclaimable cache that can be dropped without I/O
			if memUsage > inactiveFile {
				workingSet = memUsage - inactiveFile
			}
		}
	}

	return workingSet
}

// RoundToDecimal rounds a float to n decimal places
func RoundToDecimal(value float64, places int) float64 {
	shift := float64(1)
	for i := 0; i < places; i++ {
		shift *= 10
	}
	return float64(int(value*shift+0.5)) / shift
}
