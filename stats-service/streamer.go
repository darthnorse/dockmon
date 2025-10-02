package main

import (
	"context"
	"encoding/json"
	"io"
	"log"
	"sync"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/client"
)

// ContainerInfo holds basic container information
type ContainerInfo struct {
	ID      string
	Name    string
	HostID  string
	Running bool
}

// StreamManager manages persistent stats streams for all containers
type StreamManager struct {
	cache      *StatsCache
	clients    map[string]*client.Client // hostID -> Docker client
	clientsMu  sync.RWMutex
	streams    map[string]context.CancelFunc // containerID -> cancel function
	streamsMu  sync.RWMutex
	containers map[string]*ContainerInfo // containerID -> info
	containersMu sync.RWMutex
}

// NewStreamManager creates a new stream manager
func NewStreamManager(cache *StatsCache) *StreamManager {
	return &StreamManager{
		cache:      cache,
		clients:    make(map[string]*client.Client),
		streams:    make(map[string]context.CancelFunc),
		containers: make(map[string]*ContainerInfo),
	}
}

// AddDockerHost adds a Docker host client
func (sm *StreamManager) AddDockerHost(hostID, hostAddress string) error {
	sm.clientsMu.Lock()
	defer sm.clientsMu.Unlock()

	// Create Docker client for this host
	var cli *client.Client
	var err error

	if hostAddress == "" || hostAddress == "unix:///var/run/docker.sock" {
		// Local Docker socket
		cli, err = client.NewClientWithOpts(
			client.FromEnv,
			client.WithAPIVersionNegotiation(),
		)
	} else {
		// Remote Docker host
		cli, err = client.NewClientWithOpts(
			client.WithHost(hostAddress),
			client.WithAPIVersionNegotiation(),
		)
	}

	if err != nil {
		return err
	}

	sm.clients[hostID] = cli
	log.Printf("Added Docker host: %s (%s)", hostID, hostAddress)
	return nil
}

// StartStream starts a persistent stats stream for a container
func (sm *StreamManager) StartStream(ctx context.Context, containerID, containerName, hostID string) error {
	// Check if stream already exists
	sm.streamsMu.RLock()
	if _, exists := sm.streams[containerID]; exists {
		sm.streamsMu.RUnlock()
		return nil // Already streaming
	}
	sm.streamsMu.RUnlock()

	// Get Docker client for this host
	sm.clientsMu.RLock()
	cli, ok := sm.clients[hostID]
	sm.clientsMu.RUnlock()

	if !ok {
		log.Printf("Warning: No Docker client for host %s", hostID)
		return nil
	}

	// Create cancellable context for this stream
	streamCtx, cancel := context.WithCancel(ctx)

	// Store stream info
	sm.streamsMu.Lock()
	sm.streams[containerID] = cancel
	sm.streamsMu.Unlock()

	sm.containersMu.Lock()
	sm.containers[containerID] = &ContainerInfo{
		ID:      containerID,
		Name:    containerName,
		HostID:  hostID,
		Running: true,
	}
	sm.containersMu.Unlock()

	// Start streaming in a goroutine
	go sm.streamStats(streamCtx, cli, containerID, containerName, hostID)

	log.Printf("Started stats stream for container %s (%s) on host %s", containerName, containerID[:12], hostID[:12])
	return nil
}

// StopStream stops the stats stream for a container
func (sm *StreamManager) StopStream(containerID string) {
	sm.streamsMu.Lock()
	cancel, exists := sm.streams[containerID]
	if exists {
		cancel()
		delete(sm.streams, containerID)
	}
	sm.streamsMu.Unlock()

	sm.containersMu.Lock()
	if info, ok := sm.containers[containerID]; ok {
		info.Running = false
	}
	sm.containersMu.Unlock()

	// Remove from cache
	sm.cache.RemoveContainerStats(containerID)

	log.Printf("Stopped stats stream for container %s", containerID[:12])
}

// streamStats maintains a persistent stats stream for a single container
func (sm *StreamManager) streamStats(ctx context.Context, cli *client.Client, containerID, containerName, hostID string) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("Recovered from panic in stats stream for %s: %v", containerID[:12], r)
		}
	}()

	// Retry loop - restart stream if it fails
	backoff := time.Second
	maxBackoff := 30 * time.Second

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		// Open stats stream
		stats, err := cli.ContainerStats(ctx, containerID, true) // stream=true
		if err != nil {
			log.Printf("Error opening stats stream for %s: %v (retrying in %v)", containerID[:12], err, backoff)
			time.Sleep(backoff)
			backoff = min(backoff*2, maxBackoff)
			continue
		}

		// Reset backoff on successful connection
		backoff = time.Second

		// Read stats from stream
		decoder := json.NewDecoder(stats.Body)

		for {
			select {
			case <-ctx.Done():
				stats.Body.Close()
				return
			default:
			}

			var stat types.StatsJSON
			if err := decoder.Decode(&stat); err != nil {
				stats.Body.Close()
				if err == io.EOF || err == context.Canceled {
					log.Printf("Stats stream ended for %s", containerID[:12])
				} else {
					log.Printf("Error decoding stats for %s: %v", containerID[:12], err)
				}
				break // Break inner loop, will retry in outer loop
			}

			// Calculate and cache stats
			sm.processStats(&stat, containerID, containerName, hostID)
		}

		// Brief pause before reconnecting
		time.Sleep(time.Second)
	}
}

// processStats calculates metrics from raw Docker stats
func (sm *StreamManager) processStats(stat *types.StatsJSON, containerID, containerName, hostID string) {
	// Calculate CPU percentage
	cpuPercent := calculateCPUPercent(stat)

	// Memory stats
	memUsage := stat.MemoryStats.Usage
	memLimit := stat.MemoryStats.Limit
	memPercent := 0.0
	if memLimit > 0 {
		memPercent = (float64(memUsage) / float64(memLimit)) * 100.0
	}

	// Network stats
	var netRx, netTx uint64
	for _, net := range stat.Networks {
		netRx += net.RxBytes
		netTx += net.TxBytes
	}

	// Update cache
	sm.cache.UpdateContainerStats(&ContainerStats{
		ContainerID:   containerID,
		ContainerName: containerName,
		HostID:        hostID,
		CPUPercent:    roundToDecimal(cpuPercent, 1),
		MemoryUsage:   memUsage,
		MemoryLimit:   memLimit,
		MemoryPercent: roundToDecimal(memPercent, 1),
		NetworkRx:     netRx,
		NetworkTx:     netTx,
	})
}

// calculateCPUPercent calculates CPU percentage from Docker stats
func calculateCPUPercent(stat *types.StatsJSON) float64 {
	// CPU calculation similar to `docker stats` command
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

// GetStreamCount returns the number of active streams
func (sm *StreamManager) GetStreamCount() int {
	sm.streamsMu.RLock()
	defer sm.streamsMu.RUnlock()
	return len(sm.streams)
}

// StopAllStreams stops all active streams
func (sm *StreamManager) StopAllStreams() {
	sm.streamsMu.Lock()
	defer sm.streamsMu.Unlock()

	for containerID, cancel := range sm.streams {
		cancel()
		log.Printf("Stopped stream for %s", containerID[:12])
	}

	sm.streams = make(map[string]context.CancelFunc)
}

func min(a, b time.Duration) time.Duration {
	if a < b {
		return a
	}
	return b
}
