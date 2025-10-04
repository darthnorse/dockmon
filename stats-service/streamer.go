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
	ID     string
	Name   string
	HostID string
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
	// Create Docker client for this host FIRST (before acquiring lock)
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

	// Now that new client is successfully created, acquire lock and swap
	sm.clientsMu.Lock()
	defer sm.clientsMu.Unlock()

	// Close existing client if it exists (only after new one succeeds)
	if existingClient, exists := sm.clients[hostID]; exists {
		existingClient.Close()
		log.Printf("Closed existing Docker client for host %s", truncateID(hostID, 8))
	}

	sm.clients[hostID] = cli
	log.Printf("Added Docker host: %s (%s)", truncateID(hostID, 8), hostAddress)
	return nil
}

// RemoveDockerHost removes a Docker host client and stops all its streams
func (sm *StreamManager) RemoveDockerHost(hostID string) {
	// First, find all containers for this host
	sm.containersMu.RLock()
	defer sm.containersMu.RUnlock()
	containersToStop := make([]string, 0)
	for containerID, info := range sm.containers {
		if info.HostID == hostID {
			containersToStop = append(containersToStop, containerID)
		}
	}

	// Stop all streams for containers on this host
	// Do this BEFORE closing the client to avoid streams trying to use a closed client
	for _, containerID := range containersToStop {
		sm.StopStream(containerID)
	}

	// Now close and remove the Docker client
	sm.clientsMu.Lock()
	defer sm.clientsMu.Unlock()
	if cli, exists := sm.clients[hostID]; exists {
		cli.Close()
		delete(sm.clients, hostID)
		log.Printf("Removed Docker host: %s", truncateID(hostID, 8))
	}

	// Remove all stats for this host from cache
	sm.cache.RemoveHostStats(hostID)
}

// StartStream starts a persistent stats stream for a container
func (sm *StreamManager) StartStream(ctx context.Context, containerID, containerName, hostID string) error {
	// Check if stream already exists AND create if not - MUST BE ATOMIC
	sm.streamsMu.Lock()
	if _, exists := sm.streams[containerID]; exists {
		sm.streamsMu.Unlock() // Note: early return, can't use defer here
		return nil // Already streaming
	}

	// Verify Docker client exists to prevent race condition
	sm.clientsMu.RLock()
	defer sm.clientsMu.RUnlock()
	_, clientExists := sm.clients[hostID]

	if !clientExists {
		sm.streamsMu.Unlock()
		log.Printf("Warning: No Docker client for host %s", truncateID(hostID, 8))
		return nil
	}

	// Create cancellable context for this stream
	streamCtx, cancel := context.WithCancel(ctx)
	sm.streams[containerID] = cancel
	sm.streamsMu.Unlock()

	// Store container info
	sm.containersMu.Lock()
	defer sm.containersMu.Unlock()
	sm.containers[containerID] = &ContainerInfo{
		ID:     containerID,
		Name:   containerName,
		HostID: hostID,
	}

	// Verify client still exists before starting goroutine (double-check pattern)
	sm.clientsMu.RLock()
	defer sm.clientsMu.RUnlock()
	_, stillExists := sm.clients[hostID]

	if !stillExists {
		// Client was removed between checks - cleanup and exit
		sm.streamsMu.Lock()
		defer sm.streamsMu.Unlock()
		delete(sm.streams, containerID)
		cancel()
		log.Printf("Client removed before stream start for container %s", truncateID(containerID, 12))
		return nil
	}

	// Start streaming in a goroutine
	go sm.streamStats(streamCtx, containerID, containerName, hostID)

	log.Printf("Started stats stream for container %s (%s) on host %s", containerName, truncateID(containerID, 12), truncateID(hostID, 12))
	return nil
}

// StopStream stops the stats stream for a container
func (sm *StreamManager) StopStream(containerID string) {
	sm.streamsMu.Lock()
	defer sm.streamsMu.Unlock()
	cancel, exists := sm.streams[containerID]
	if exists {
		cancel()
		delete(sm.streams, containerID)
	}

	sm.containersMu.Lock()
	defer sm.containersMu.Unlock()
	delete(sm.containers, containerID)

	// Remove from cache
	sm.cache.RemoveContainerStats(containerID)

	log.Printf("Stopped stats stream for container %s", truncateID(containerID, 12))
}

// streamStats maintains a persistent stats stream for a single container
func (sm *StreamManager) streamStats(ctx context.Context, containerID, containerName, hostID string) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("Recovered from panic in stats stream for %s: %v", truncateID(containerID, 12), r)
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

		// Get current Docker client (may have changed if host was updated)
		sm.clientsMu.RLock()
		cli, ok := sm.clients[hostID]
		sm.clientsMu.RUnlock() // Manual unlock needed - we're in a loop

		if !ok {
			log.Printf("No Docker client for host %s (container %s), retrying in %v", truncateID(hostID, 8), truncateID(containerID, 12), backoff)
			time.Sleep(backoff)
			backoff = min(backoff*2, maxBackoff)
			continue
		}

		// Open stats stream
		stats, err := cli.ContainerStats(ctx, containerID, true) // stream=true
		if err != nil {
			log.Printf("Error opening stats stream for %s: %v (retrying in %v)", truncateID(containerID, 12), err, backoff)
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
					log.Printf("Stats stream ended for %s", truncateID(containerID, 12))
				} else {
					log.Printf("Error decoding stats for %s: %v", truncateID(containerID, 12), err)
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

	// Disk I/O stats
	var diskRead, diskWrite uint64
	for _, bio := range stat.BlkioStats.IoServiceBytesRecursive {
		if bio.Op == "Read" {
			diskRead += bio.Value
		} else if bio.Op == "Write" {
			diskWrite += bio.Value
		}
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
		DiskRead:      diskRead,
		DiskWrite:     diskWrite,
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

// StopAllStreams stops all active streams and closes all Docker clients
func (sm *StreamManager) StopAllStreams() {
	// Stop all streams
	sm.streamsMu.Lock()
	for containerID, cancel := range sm.streams {
		cancel()
		log.Printf("Stopped stream for %s", truncateID(containerID, 12))
	}
	sm.streams = make(map[string]context.CancelFunc)
	sm.streamsMu.Unlock()

	// Close all Docker clients
	sm.clientsMu.Lock()
	for hostID, cli := range sm.clients {
		cli.Close()
		log.Printf("Closed Docker client for host %s", truncateID(hostID, 8))
	}
	sm.clients = make(map[string]*client.Client)
	sm.clientsMu.Unlock()
}

func min(a, b time.Duration) time.Duration {
	if a < b {
		return a
	}
	return b
}
