package main

import (
	"context"
	"log"
	"time"

	dockerpkg "github.com/darthnorse/dockmon-shared/docker"
	"github.com/darthnorse/dockmon-shared/hostdisk"
	"github.com/dockmon/stats-service/persistence"
)

// streamManagerIface is the subset of *StreamManager that Aggregator needs.
// Defined as an interface so tests can fake it without standing up a real
// StreamManager (which requires Docker clients).
type streamManagerIface interface {
	HasHost(hostID string) bool
	DockerRootDir(ctx context.Context, hostID string) (string, error)
}

// Aggregator aggregates container stats into host-level metrics
type Aggregator struct {
	cache             *StatsCache
	streamManager     streamManagerIface
	aggregateInterval time.Duration
	hostProcReader    *HostProcReader
	cascade           *persistence.Cascade // optional; nil disables persistence ingest

	// diskProber measures the local host's filesystem through /hostfs; nil
	// disables disk. diskReaders memoize the data-root per local host and are
	// only touched from the aggregation goroutine.
	diskProber  *hostdisk.Prober
	diskReaders map[string]*hostdisk.Reader
}

// NewAggregator creates a new aggregator
func NewAggregator(cache *StatsCache, streamManager *StreamManager, interval time.Duration) *Aggregator {
	hostProcReader := NewHostProcReader()
	if hostProcReader.IsAvailable() {
		log.Println("Host /proc mounted at /host/proc - using actual host CPU/memory stats for local host")
	}

	diskProber := hostdisk.NewProber(hostdisk.DefaultHostRoot)
	if mounted, err := diskProber.HostRootMounted(); err != nil {
		log.Printf("Could not verify the %s mount (%v) - host disk usage will not be reported for the local host", hostdisk.DefaultHostRoot, err)
	} else if !mounted {
		log.Printf("Host root not mounted at %s - host disk usage unavailable for the local host; add -v /:/hostfs:ro to enable disk_percent alerts", hostdisk.DefaultHostRoot)
	} else {
		log.Printf("Host root mounted at %s - reporting host disk usage for the local host", hostdisk.DefaultHostRoot)
	}

	return &Aggregator{
		cache:             cache,
		streamManager:     streamManager,
		aggregateInterval: interval,
		hostProcReader:    hostProcReader,
		diskProber:        diskProber,
		diskReaders:       make(map[string]*hostdisk.Reader),
	}
}

// localHostDisk reads the local host's disk usage, or nil when it cannot be
// measured. Independent of /host/proc: a host with /hostfs but no /host/proc
// still gets disk, and a disk failure never suppresses CPU and memory.
func (a *Aggregator) localHostDisk(hostID string) *hostdisk.HostDisk {
	if a.diskProber == nil || !a.cache.IsHostLocal(hostID) {
		return nil
	}
	reader, ok := a.diskReaders[hostID]
	if !ok {
		reader = hostdisk.NewReader(a.diskProber, func(ctx context.Context) (string, error) {
			return a.streamManager.DockerRootDir(ctx, hostID)
		}, log.Printf)
		a.diskReaders[hostID] = reader
	}

	ctx, cancel := context.WithTimeout(context.Background(), dockerInfoTimeout)
	defer cancel()
	reading, err := reader.Read(ctx)
	if err != nil {
		return nil
	}
	return reading.Wire()
}

// pruneDiskReaders drops readers for hosts that are no longer local, so a
// removed host does not leave its reader behind.
func (a *Aggregator) pruneDiskReaders() {
	for hostID := range a.diskReaders {
		if !a.cache.IsHostLocal(hostID) {
			delete(a.diskReaders, hostID)
		}
	}
}

// dockerInfoTimeout bounds the one-off data-root lookup so a wedged daemon
// cannot stall the aggregation loop.
const dockerInfoTimeout = 5 * time.Second

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
	a.pruneDiskReaders()
	containerStats := a.cache.GetAllContainerStats()

	// Group containers by host
	hostContainers := make(map[string][]*ContainerStats)
	for _, stats := range containerStats {
		hostContainers[stats.HostID] = append(hostContainers[stats.HostID], stats)
	}

	for hostID, containers := range hostContainers {
		// Read the agent's sample once: checking freshness separately from
		// building the sample lets a reading that lands in between authorize
		// persisting the container-derived fallback.
		agentSample := a.freshAgentSample(hostID)
		hostStats := a.aggregateHostStats(hostID, containers, agentSample)

		// Push to live dashboard cache only for hosts with a registered
		// Docker client. Agent hosts are written exclusively by the ingest
		// handler, from the agent's real /proc readings — aggregating their
		// containers here would be wrong anyway, since agent hosts carry no
		// CPU-count or host-memory metadata in this cache.
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
			// An agent's own reading counts as fresh data in its own right:
			// the evaluator alerts on it whether or not containers report.
			if freshCount > 0 || agentSample != nil {
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

	// An agent host whose container entries have aged out of the cache never
	// appears in the grouping above, but it is still reporting itself and the
	// evaluator is still alerting on it.
	if a.cascade != nil && settingsProvider.PersistEnabled() {
		now := time.Now()
		for hostID := range a.cache.GetAllHostStats() {
			if _, grouped := hostContainers[hostID]; grouped {
				continue
			}
			agentSample := a.freshAgentSample(hostID)
			if agentSample == nil {
				continue
			}
			a.cascade.Ingest(hostID, true, now, sampleFromHostStats(agentSample, 0))
		}
	}
}

// agentSampleMaxAge matches the alert evaluator's freshness window
// (STATS_MAX_AGE_SECONDS in backend/alerts/capabilities.py). A shorter window
// here would put the container aggregate back on the chart while the evaluator
// was still alerting on the agent's reading.
const agentSampleMaxAge = 60 * time.Second

// freshAgentSample returns the agent's own host reading for an agent-owned
// host, or nil when the host is a registered Docker host or has no recent
// sample. Docker hosts are excluded because the aggregator writes their cache
// entry itself — reading it back would be a feedback loop.
func (a *Aggregator) freshAgentSample(hostID string) *HostStats {
	if a.streamManager.HasHost(hostID) {
		return nil
	}
	stats, ok := a.cache.GetHostStats(hostID)
	if !ok || time.Since(stats.LastUpdate) > agentSampleMaxAge {
		return nil
	}
	return stats
}

// aggregateHostStats aggregates stats for a single host
// agentSample is the host's own reading when it is agent-owned and fresh, read
// once by the caller so freshness and the persisted values cannot disagree.
func (a *Aggregator) aggregateHostStats(hostID string, containers []*ContainerStats, agentSample *HostStats) *HostStats {
	stats := a.aggregateHostCPUMemory(hostID, containers, agentSample)
	// Rebuilt every cycle, so a failed read clears the previous value instead
	// of leaving a last-known-good number for alerts to keep firing on.
	stats.HostDisk = a.localHostDisk(hostID)
	return stats
}

// aggregateHostCPUMemory picks the CPU/memory source for a host: /host/proc
// for the local host, the agent's own reading for an agent host, otherwise a
// container aggregate.
func (a *Aggregator) aggregateHostCPUMemory(hostID string, containers []*ContainerStats, agentSample *HostStats) *HostStats {
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

	// Agent-owned host: use the ingest handler's real /proc reading so history
	// matches what the evaluator alerts on. A nil sample (no /host/proc mount)
	// falls through — the evaluator has no host data for that host either.
	if agentSample != nil {
		return &HostStats{
			HostID:           hostID,
			CPUPercent:       agentSample.CPUPercent,
			MemoryPercent:    agentSample.MemoryPercent,
			MemoryUsedBytes:  agentSample.MemoryUsedBytes,
			MemoryLimitBytes: agentSample.MemoryLimitBytes,
			NetworkRxBytes:   totalNetRx,
			NetworkTxBytes:   totalNetTx,
			ContainerCount:   validContainers,
		}
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

	hostMemLimit := a.cache.GetHostMemory(hostID)
	if hostMemLimit == 0 {
		hostMemLimit = totalMemLimit
	}
	if hostMemLimit > 0 {
		memPercent = (float64(totalMemUsage) / float64(hostMemLimit)) * 100.0
	}

	// Round to 1 decimal place - using shared package
	cpuPercent = dockerpkg.RoundToDecimal(cpuPercent, 1)
	memPercent = dockerpkg.RoundToDecimal(memPercent, 1)

	return &HostStats{
		HostID:           hostID,
		CPUPercent:       cpuPercent,
		MemoryPercent:    memPercent,
		MemoryUsedBytes:  totalMemUsage,
		MemoryLimitBytes: hostMemLimit,
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
