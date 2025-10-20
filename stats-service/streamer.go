package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"strings"
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

// createTLSOption creates a Docker client TLS option from PEM-encoded certificates
func createTLSOption(caCertPEM, certPEM, keyPEM string) (client.Opt, error) {
	// Parse CA certificate
	caCertPool := x509.NewCertPool()
	if !caCertPool.AppendCertsFromPEM([]byte(caCertPEM)) {
		return nil, fmt.Errorf("failed to parse CA certificate")
	}

	// Parse client certificate and key
	clientCert, err := tls.X509KeyPair([]byte(certPEM), []byte(keyPEM))
	if err != nil {
		return nil, fmt.Errorf("failed to parse client certificate/key: %v", err)
	}

	// Create TLS config
	tlsConfig := &tls.Config{
		Certificates: []tls.Certificate{clientCert},
		RootCAs:      caCertPool,
		MinVersion:   tls.VersionTLS12,
	}

	// Create HTTP client with TLS transport and timeouts
	// Note: No overall Timeout set because Docker API streaming operations (stats, events)
	// are long-running connections that should not be killed by a timeout
	httpClient := &http.Client{
		Transport: &http.Transport{
			DialContext: (&net.Dialer{
				Timeout:   30 * time.Second, // Connection establishment timeout
				KeepAlive: 30 * time.Second, // TCP keepalive interval
			}).DialContext,
			TLSClientConfig:       tlsConfig,
			TLSHandshakeTimeout:   10 * time.Second,
			IdleConnTimeout:       90 * time.Second,
			ResponseHeaderTimeout: 10 * time.Second,
		},
	}

	return client.WithHTTPClient(httpClient), nil
}

// StreamManager manages persistent stats streams for all containers
type StreamManager struct {
	cache      *StatsCache
	clients    map[string]*client.Client // hostID -> Docker client
	clientsMu  sync.RWMutex
	hostNames  map[string]string // hostID -> host name (for logging)
	hostNamesMu sync.RWMutex
	streams    map[string]context.CancelFunc // composite key (hostID:containerID) -> cancel function
	streamsMu  sync.RWMutex
	containers map[string]*ContainerInfo // composite key (hostID:containerID) -> info
	containersMu sync.RWMutex
}

// NewStreamManager creates a new stream manager
func NewStreamManager(cache *StatsCache) *StreamManager {
	return &StreamManager{
		cache:      cache,
		clients:    make(map[string]*client.Client),
		hostNames:  make(map[string]string),
		streams:    make(map[string]context.CancelFunc),
		containers: make(map[string]*ContainerInfo),
	}
}

// AddDockerHost adds a Docker host client
func (sm *StreamManager) AddDockerHost(hostID, hostName, hostAddress, tlsCACert, tlsCert, tlsKey string) error {
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
		// Remote Docker host - check if TLS is needed
		clientOpts := []client.Opt{
			client.WithHost(hostAddress),
			client.WithAPIVersionNegotiation(),
		}

		// If TLS certificates provided, configure TLS
		if tlsCACert != "" && tlsCert != "" && tlsKey != "" {
			tlsOpt, err := createTLSOption(tlsCACert, tlsCert, tlsKey)
			if err != nil {
				return fmt.Errorf("failed to create TLS config: %v", err)
			}
			clientOpts = append(clientOpts, tlsOpt)
		}

		cli, err = client.NewClientWithOpts(clientOpts...)
	}

	if err != nil {
		return err
	}

	// Track whether client was successfully stored to prevent leak
	clientStored := false
	defer func() {
		if !clientStored && cli != nil {
			cli.Close()
			log.Printf("Cleaned up unstored Docker client for host %s", truncateID(hostID, 8))
		}
	}()

	// Now that new client is successfully created, acquire lock and swap
	sm.clientsMu.Lock()
	defer sm.clientsMu.Unlock()

	// Close existing client if it exists (only after new one succeeds)
	if existingClient, exists := sm.clients[hostID]; exists {
		existingClient.Close()
		log.Printf("Closed existing Docker client for host %s (%s)", hostName, truncateID(hostID, 8))
	}

	sm.clients[hostID] = cli
	clientStored = true // Mark as successfully stored

	// Store host name for logging
	sm.hostNamesMu.Lock()
	sm.hostNames[hostID] = hostName
	sm.hostNamesMu.Unlock()

	log.Printf("Added Docker host: %s (%s) at %s", hostName, truncateID(hostID, 8), hostAddress)

	// Initialize host stats with zero values so the host appears immediately in the UI
	sm.cache.UpdateHostStats(&HostStats{
		HostID:         hostID,
		ContainerCount: 0,
	})

	return nil
}

// RemoveDockerHost removes a Docker host client and stops all its streams
func (sm *StreamManager) RemoveDockerHost(hostID string) {
	// First, find all containers for this host
	sm.containersMu.RLock()
	containersToStop := make([]string, 0)
	for compositeKey, info := range sm.containers {
		if info.HostID == hostID {
			containersToStop = append(containersToStop, compositeKey)
		}
	}
	sm.containersMu.RUnlock()

	// Stop all streams for containers on this host
	// Do this BEFORE closing the client to avoid streams trying to use a closed client
	for _, compositeKey := range containersToStop {
		// Extract container ID from composite key (format: hostID:containerID)
		parts := strings.SplitN(compositeKey, ":", 2)
		if len(parts) == 2 {
			sm.StopStream(parts[1], parts[0]) // containerID, hostID
		}
	}

	// Now close and remove the Docker client
	sm.clientsMu.Lock()
	defer sm.clientsMu.Unlock()
	if cli, exists := sm.clients[hostID]; exists {
		hostName := sm.getHostName(hostID)
		cli.Close()
		delete(sm.clients, hostID)
		log.Printf("Removed Docker host: %s (%s)", hostName, truncateID(hostID, 8))
	}

	// Remove host name
	sm.hostNamesMu.Lock()
	delete(sm.hostNames, hostID)
	sm.hostNamesMu.Unlock()

	// Remove all stats for this host from cache
	sm.cache.RemoveHostStats(hostID)
}

// StartStream starts a persistent stats stream for a container
func (sm *StreamManager) StartStream(ctx context.Context, containerID, containerName, hostID string) error {
	// Create composite key to support containers with duplicate IDs on different hosts
	compositeKey := fmt.Sprintf("%s:%s", hostID, containerID)

	// Acquire locks in consistent order: clientsMu → streamsMu → containersMu (when needed)
	sm.clientsMu.RLock()
	sm.streamsMu.Lock()

	// Check if stream already exists
	if _, exists := sm.streams[compositeKey]; exists {
		sm.streamsMu.Unlock()
		sm.clientsMu.RUnlock()
		return nil // Already streaming
	}

	// Check if client exists
	_, clientExists := sm.clients[hostID]
	if !clientExists {
		sm.streamsMu.Unlock()
		sm.clientsMu.RUnlock()
		hostName := sm.getHostName(hostID)
		log.Printf("Warning: No Docker client for host %s (%s)", hostName, truncateID(hostID, 8))
		return nil
	}

	// Create cancellable context for this stream
	streamCtx, cancel := context.WithCancel(ctx)
	sm.streams[compositeKey] = cancel

	// Release locks before acquiring containersMu to prevent nested locking
	sm.streamsMu.Unlock()
	sm.clientsMu.RUnlock()

	// Store container info with separate lock
	sm.containersMu.Lock()
	sm.containers[compositeKey] = &ContainerInfo{
		ID:     containerID,
		Name:   containerName,
		HostID: hostID,
	}
	sm.containersMu.Unlock()

	// Start streaming goroutine (no locks held)
	go sm.streamStats(streamCtx, containerID, containerName, hostID)

	hostName := sm.getHostName(hostID)
	log.Printf("Started stats stream for container %s (%s) on host %s (%s)", containerName, truncateID(containerID, 12), hostName, truncateID(hostID, 8))
	return nil
}

// StopStream stops the stats stream for a container
func (sm *StreamManager) StopStream(containerID, hostID string) {
	// Create composite key to support containers with duplicate IDs on different hosts
	compositeKey := fmt.Sprintf("%s:%s", hostID, containerID)

	sm.streamsMu.Lock()
	defer sm.streamsMu.Unlock()
	cancel, exists := sm.streams[compositeKey]
	if exists {
		cancel()
		delete(sm.streams, compositeKey)
	}

	sm.containersMu.Lock()
	defer sm.containersMu.Unlock()
	delete(sm.containers, compositeKey)

	// Remove from cache
	sm.cache.RemoveContainerStats(containerID, hostID)

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
			hostName := sm.getHostName(hostID)
			log.Printf("No Docker client for host %s (%s) (container %s), retrying in %v", hostName, truncateID(hostID, 8), truncateID(containerID, 12), backoff)
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

// getHostName safely retrieves the host name for logging (returns truncated ID if name not found)
func (sm *StreamManager) getHostName(hostID string) string {
	sm.hostNamesMu.RLock()
	defer sm.hostNamesMu.RUnlock()
	if name, ok := sm.hostNames[hostID]; ok {
		return name
	}
	return truncateID(hostID, 8) // Fallback to short ID
}

// HasHost checks if a Docker host is registered
func (sm *StreamManager) HasHost(hostID string) bool {
	sm.clientsMu.RLock()
	defer sm.clientsMu.RUnlock()
	_, exists := sm.clients[hostID]
	return exists
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
		hostName := sm.getHostName(hostID)
		cli.Close()
		log.Printf("Closed Docker client for host %s (%s)", hostName, truncateID(hostID, 8))
	}
	sm.clients = make(map[string]*client.Client)
	sm.clientsMu.Unlock()

	// Clear all host names
	sm.hostNamesMu.Lock()
	sm.hostNames = make(map[string]string)
	sm.hostNamesMu.Unlock()
}

func min(a, b time.Duration) time.Duration {
	if a < b {
		return a
	}
	return b
}
