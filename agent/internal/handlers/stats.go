package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"sync"
	"time"

	sharedDocker "github.com/darthnorse/dockmon-shared/docker"
	"github.com/darthnorse/dockmon-agent/internal/client/statsmsg"
	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/docker/docker/api/types/container"
	"github.com/sirupsen/logrus"
)

// StatsServiceSender is the narrow interface the StatsHandler uses to ship
// stats samples to stats-service. *client.StatsServiceClient satisfies this
// interface structurally — handlers cannot import `client` directly because
// `client` already imports `handlers` for the main WebSocket client.
type StatsServiceSender interface {
	Send(msg statsmsg.AgentStatsMsg)
}

// StatsHandler manages container stats collection and streaming
type StatsHandler struct {
	dockerClient *docker.Client
	log          *logrus.Logger

	// Active stats streams
	streams   map[string]context.CancelFunc
	streamsMu sync.RWMutex

	// Callback to send stats to backend
	sendMessage func(msgType string, payload interface{}) error

	// Optional: if non-nil, stats are also dual-sent to stats-service for
	// historical persistence. nil disables the dual-send. See spec §10.
	statsService StatsServiceSender
}

// NewStatsHandler creates a new stats handler
func NewStatsHandler(dockerClient *docker.Client, log *logrus.Logger, sendMessage func(string, interface{}) error) *StatsHandler {
	return &StatsHandler{
		dockerClient: dockerClient,
		log:          log,
		streams:      make(map[string]context.CancelFunc),
		sendMessage:  sendMessage,
	}
}

// SetStatsServiceClient enables dual-send to stats-service. Pass nil to disable.
// The constructor leaves statsService nil; the agent main loop (Task 22) wires
// it up after the stats-service WebSocket client is built. Accepts any
// implementation of StatsServiceSender; *client.StatsServiceClient satisfies
// the interface structurally.
func (h *StatsHandler) SetStatsServiceClient(c StatsServiceSender) {
	// A typed-nil *client.StatsServiceClient passed as an interface is NOT
	// == untyped nil, so a plain `c == nil` check lets a typed nil through
	// and processStats then panics on the nil receiver. Normalize both cases
	// here so the only contract callers need to honor is "pass nil (typed or
	// untyped) to disable dual-send."
	if c == nil || isNilPointer(c) {
		h.statsService = nil
		return
	}
	h.statsService = c
}

// isNilPointer reports whether v is an interface value wrapping a nil
// pointer (the "typed nil" footgun). It returns false for non-pointer
// concrete types, for non-nil pointers, and for an already-nil interface
// (callers should check `c == nil` separately for clarity).
func isNilPointer(v interface{}) bool {
	rv := reflect.ValueOf(v)
	return rv.Kind() == reflect.Ptr && rv.IsNil()
}

// StartStatsCollection begins stats collection for all running containers
func (h *StatsHandler) StartStatsCollection(ctx context.Context) error {
	// List all containers
	containers, err := h.dockerClient.ListContainers(ctx)
	if err != nil {
		return fmt.Errorf("failed to list containers: %w", err)
	}

	h.log.Infof("Starting stats collection for %d containers", len(containers))

	// Start stats stream for each running container
	for _, container := range containers {
		if container.State == "running" {
			if err := h.StartContainerStats(ctx, container.ID, container.Names[0]); err != nil {
				h.log.Errorf("Failed to start stats for container %s: %v", container.ID, err)
				// Continue with other containers
			}
		}
	}

	return nil
}

// StartContainerStats starts stats collection for a specific container
func (h *StatsHandler) StartContainerStats(parentCtx context.Context, containerID, containerName string) error {
	h.streamsMu.Lock()
	defer h.streamsMu.Unlock()

	// Check if already streaming
	if _, exists := h.streams[containerID]; exists {
		h.log.Debugf("Stats stream already exists for container %s", containerID)
		return nil
	}

	// Create cancellable context for this stream
	ctx, cancel := context.WithCancel(parentCtx) // #nosec G118
	h.streams[containerID] = cancel

	// Start stats collection in goroutine
	go h.collectStats(ctx, containerID, containerName)

	h.log.Infof("Started stats collection for container %s (%s)", containerName, safeShortID(containerID))
	return nil
}

// StopContainerStats stops stats collection for a specific container
func (h *StatsHandler) StopContainerStats(containerID string) {
	h.streamsMu.Lock()
	defer h.streamsMu.Unlock()

	if cancel, exists := h.streams[containerID]; exists {
		cancel()
		delete(h.streams, containerID)
		h.log.Infof("Stopped stats collection for container %s", safeShortID(containerID))
	}
}

// StopAll stops all stats collection
func (h *StatsHandler) StopAll() {
	h.streamsMu.Lock()
	defer h.streamsMu.Unlock()

	for containerID, cancel := range h.streams {
		cancel()
		h.log.Debugf("Stopped stats stream for %s", safeShortID(containerID))
	}
	h.streams = make(map[string]context.CancelFunc)
	h.log.Info("Stopped all stats collection")
}

// collectStats collects stats for a single container
func (h *StatsHandler) collectStats(ctx context.Context, containerID, containerName string) {
	defer func() {
		h.streamsMu.Lock()
		delete(h.streams, containerID)
		h.streamsMu.Unlock()
	}()

	// Docker stats stream (stream = true)
	stream, err := h.dockerClient.ContainerStats(ctx, containerID, true)
	if err != nil {
		h.log.Errorf("Failed to open stats stream for %s: %v", safeShortID(containerID), err)
		return
	}
	defer stream.Body.Close()

	decoder := json.NewDecoder(stream.Body)

	for {
		select {
		case <-ctx.Done():
			h.log.Debugf("Stats collection cancelled for %s", safeShortID(containerID))
			return
		default:
			var stats container.StatsResponse
			if err := decoder.Decode(&stats); err != nil {
				h.log.Errorf("Failed to decode stats for %s: %v", safeShortID(containerID), err)
				return
			}

			// Process stats using shared package
			h.processStats(&stats, containerID, containerName)
		}
	}
}

// processStats processes raw Docker stats and sends to backend
func (h *StatsHandler) processStats(stat *container.StatsResponse, containerID, containerName string) {
	// Use shared package to calculate stats (same logic as stats-service!)
	result := sharedDocker.CalculateStats(stat)

	// Prepare stats message
	statsMsg := map[string]interface{}{
		"container_id":    containerID,
		"container_name":  containerName,
		"cpu_percent":     sharedDocker.RoundToDecimal(result.CPUPercent, 1),
		"memory_usage":    result.MemoryUsage,
		"memory_limit":    result.MemoryLimit,
		"memory_percent":  sharedDocker.RoundToDecimal(result.MemoryPercent, 1),
		"network_rx":      result.NetworkRx,
		"network_tx":      result.NetworkTx,
		"disk_read":       result.DiskRead,
		"disk_write":      result.DiskWrite,
		"timestamp":       time.Now().UTC().Format(time.RFC3339),
	}

	// Send to backend via WebSocket
	if err := h.sendMessage("container_stats", statsMsg); err != nil {
		h.log.Errorf("Failed to send stats for %s: %v", safeShortID(containerID), err)
	}

	// Dual-send to stats-service for historical persistence (spec §10).
	// nil-safe: disabled until the agent main loop calls SetStatsServiceClient.
	if h.statsService != nil {
		h.statsService.Send(statsmsg.AgentStatsMsg{
			ContainerID:   containerID,
			ContainerName: containerName,
			CPUPercent:    sharedDocker.RoundToDecimal(result.CPUPercent, 1),
			MemoryUsage:   result.MemoryUsage,
			MemoryLimit:   result.MemoryLimit,
			MemoryPercent: sharedDocker.RoundToDecimal(result.MemoryPercent, 1),
			NetworkRx:     result.NetworkRx,
			NetworkTx:     result.NetworkTx,
			DiskRead:      result.DiskRead,
			DiskWrite:     result.DiskWrite,
			Timestamp:     time.Now().UTC().Format(time.RFC3339),
		})
	}
}
