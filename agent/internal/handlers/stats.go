package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand"
	"sync"
	"time"

	cerrdefs "github.com/containerd/errdefs"
	"github.com/darthnorse/dockmon-agent/internal/client/statsmsg"
	"github.com/darthnorse/dockmon-agent/internal/docker"
	sharedDocker "github.com/darthnorse/dockmon-shared/docker"
	"github.com/docker/docker/api/types/container"
	"github.com/sirupsen/logrus"
)

const (
	statsRetryInitialBackoff = 1 * time.Second
	statsRetryMaxBackoff     = 30 * time.Second

	// An attempt counts as stable — and so resets the backoff — only after it
	// has carried live samples for this long. Resetting on the first sample
	// lets a stream that dies right after one frame retry every second.
	statsStreamStableAfter = 30 * time.Second

	// The daemon publishes roughly one frame per second even for a stopped
	// container, so a stream that goes quiet is wedged, not idle.
	statsStreamIdleTimeout = 60 * time.Second

	statsWarnInterval = 5 * time.Minute
)

// errStreamNotLive ends an attempt when the daemon serves zero-read frames:
// the stream is open but the container is not running. Expected, not a fault.
var errStreamNotLive = errors.New("stats stream is not live")

// statsDockerClient is the Docker surface this handler needs. *docker.Client
// satisfies it; tests substitute a fake.
type statsDockerClient interface {
	ListContainers(ctx context.Context) ([]docker.ContainerWithDigest, error)
	ContainerStats(ctx context.Context, containerID string, stream bool) (container.StatsResponseReader, error)
}

// statsStream is one collector registration. Its pointer identity is the token
// the collector uses to release only its own entry.
type statsStream struct {
	cancel context.CancelFunc
}

// StatsHandler manages container stats collection and streaming
type StatsHandler struct {
	dockerClient statsDockerClient
	log          *logrus.Logger

	// Active stats streams
	streams   map[string]*statsStream
	streamsMu sync.RWMutex

	// Callback to send stats to backend
	sendMessage func(msgType string, payload interface{}) error

	// Retry timing, as fields so tests can drive the loop without real delays.
	wait         func(ctx context.Context, d time.Duration) bool
	now          func() time.Time
	idleTimeout  time.Duration
	stableAfter  time.Duration
	warnInterval time.Duration

	// Dual-send to stats-service for historical persistence; disabled while
	// no client is attached. See spec §10.
	statsSink
}

// NewStatsHandler creates a new stats handler
func NewStatsHandler(dockerClient *docker.Client, log *logrus.Logger, sendMessage func(string, interface{}) error) *StatsHandler {
	return newStatsHandler(dockerClient, log, sendMessage)
}

func newStatsHandler(dockerClient statsDockerClient, log *logrus.Logger, sendMessage func(string, interface{}) error) *StatsHandler {
	return &StatsHandler{
		dockerClient: dockerClient,
		log:          log,
		streams:      make(map[string]*statsStream),
		sendMessage:  sendMessage,
		wait:         waitWithJitter,
		now:          time.Now,
		idleTimeout:  statsStreamIdleTimeout,
		stableAfter:  statsStreamStableAfter,
		warnInterval: statsWarnInterval,
	}
}

// waitWithJitter sleeps for d (±20%) and reports whether it completed. The
// jitter keeps a daemon restart from resynchronising every collector.
func waitWithJitter(ctx context.Context, d time.Duration) bool {
	if d > 0 {
		spread := int64(d / 5)
		if spread > 0 {
			d += time.Duration(rand.Int63n(2*spread) - spread) // #nosec G404 -- retry jitter, not security
		}
	}
	timer := time.NewTimer(d)
	defer timer.Stop()

	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
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
	for _, c := range containers {
		if c.State != "running" {
			continue
		}
		name := ""
		if len(c.Names) > 0 {
			name = c.Names[0]
		}
		if err := h.StartContainerStats(ctx, c.ID, name); err != nil {
			h.log.Errorf("Failed to start stats for container %s: %v", c.ID, err)
			// Continue with other containers
		}
	}

	return nil
}

// StartContainerStats starts stats collection for a specific container
func (h *StatsHandler) StartContainerStats(parentCtx context.Context, containerID, containerName string) error {
	h.streamsMu.Lock()
	defer h.streamsMu.Unlock()

	// Checked under the lock so a start racing teardown cannot register an
	// entry bound to a dead context — the next connection would see it and
	// skip the container.
	if parentCtx.Err() != nil {
		h.log.Debugf("Not starting stats for %s: context already cancelled", safeShortID(containerID))
		return nil
	}

	// Check if already streaming
	if _, exists := h.streams[containerID]; exists {
		h.log.Debugf("Stats stream already exists for container %s", containerID)
		return nil
	}

	// Create cancellable context for this stream
	ctx, cancel := context.WithCancel(parentCtx) // #nosec G118
	stream := &statsStream{cancel: cancel}
	h.streams[containerID] = stream

	// Start stats collection in goroutine
	go h.collectStats(ctx, containerID, containerName, stream)

	h.log.Infof("Started stats collection for container %s (%s)", containerName, safeShortID(containerID))
	return nil
}

// StopContainerStats stops stats collection for a specific container
func (h *StatsHandler) StopContainerStats(containerID string) {
	h.streamsMu.Lock()
	defer h.streamsMu.Unlock()

	if stream, exists := h.streams[containerID]; exists {
		stream.cancel()
		delete(h.streams, containerID)
		h.log.Infof("Stopped stats collection for container %s", safeShortID(containerID))
	}
}

// StopAll stops all stats collection
func (h *StatsHandler) StopAll() {
	h.streamsMu.Lock()
	defer h.streamsMu.Unlock()

	for containerID, stream := range h.streams {
		stream.cancel()
		h.log.Debugf("Stopped stats stream for %s", safeShortID(containerID))
	}
	h.streams = make(map[string]*statsStream)
	h.log.Info("Stopped all stats collection")
}

// releaseStream deregisters a collector, but only if the registration is still
// its own: a departing goroutine must never delete a newer collector's entry.
func (h *StatsHandler) releaseStream(containerID string, stream *statsStream) {
	h.streamsMu.Lock()
	defer h.streamsMu.Unlock()

	if current, exists := h.streams[containerID]; exists && current == stream {
		delete(h.streams, containerID)
	}
	stream.cancel()
}

// collectorState carries what has to survive across attempts: how many have
// failed since the last live sample, and when we last said so out loud.
type collectorState struct {
	failures int
	lastWarn time.Time
}

// collectStats collects stats for a single container, reopening the stream for
// as long as the collector is registered. It stops only on cancellation or
// when the container no longer exists.
func (h *StatsHandler) collectStats(ctx context.Context, containerID, containerName string, stream *statsStream) {
	defer h.releaseStream(containerID, stream)

	state := &collectorState{}
	backoff := statsRetryInitialBackoff

	for {
		if ctx.Err() != nil {
			h.log.Debugf("Stats collection cancelled for %s", safeShortID(containerID))
			return
		}

		stable, err := h.streamContainerStats(ctx, containerID, containerName, state)

		if ctx.Err() != nil {
			h.log.Debugf("Stats collection cancelled for %s", safeShortID(containerID))
			return
		}
		if cerrdefs.IsNotFound(err) {
			h.log.Infof("Stopping stats collection for %s: container no longer exists", safeShortID(containerID))
			return
		}

		if stable {
			backoff = statsRetryInitialBackoff
		}
		h.logAttemptFailure(state, containerID, err, backoff)

		if !h.wait(ctx, backoff) {
			h.log.Debugf("Stats collection cancelled for %s", safeShortID(containerID))
			return
		}

		backoff *= 2
		if backoff > statsRetryMaxBackoff {
			backoff = statsRetryMaxBackoff
		}
	}
}

// streamContainerStats runs a single stream attempt. It reports whether the
// attempt was stable enough to reset the retry backoff, plus the error that
// ended it.
func (h *StatsHandler) streamContainerStats(ctx context.Context, containerID, containerName string, state *collectorState) (bool, error) {
	// The attempt owns the request context so the idle watchdog can abort a
	// wedged read; cancelling the stream's own context is what unblocks Decode.
	attemptCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	stream, err := h.dockerClient.ContainerStats(attemptCtx, containerID, true)
	if err != nil {
		return false, err
	}
	defer stream.Body.Close()

	idle := time.AfterFunc(h.idleTimeout, cancel)
	defer idle.Stop()

	decoder := json.NewDecoder(stream.Body)
	started := h.now()
	live := false

	for {
		if err := attemptCtx.Err(); err != nil {
			return h.attemptWasStable(live, started), err
		}

		var stats container.StatsResponse
		if err := decoder.Decode(&stats); err != nil {
			return h.attemptWasStable(live, started), err
		}

		// The frame was already in flight when cancellation landed; sending it
		// now would put it on a socket the next connection owns.
		if err := attemptCtx.Err(); err != nil {
			return h.attemptWasStable(live, started), err
		}

		// A zero read timestamp is how the daemon reports "subscribed, but this
		// container is not running". Publishing it would look like a healthy
		// idle container on both the UI and the alert wire.
		if stats.Read.IsZero() {
			return h.attemptWasStable(live, started), errStreamNotLive
		}

		idle.Reset(h.idleTimeout)
		if !live {
			live = true
			h.logRecovery(state, containerID)
		}

		// Process stats using shared package
		h.processStats(&stats, containerID, containerName)
	}
}

func (h *StatsHandler) attemptWasStable(live bool, started time.Time) bool {
	return live && h.now().Sub(started) >= h.stableAfter
}

// logRecovery reports a stream coming back, once per run of failures. It has to
// happen here rather than in the retry loop: a healthy stream never returns to
// that loop.
func (h *StatsHandler) logRecovery(state *collectorState, containerID string) {
	if state.failures == 0 {
		return
	}
	h.log.Infof("Stats stream for %s recovered after %d failed attempt(s)", safeShortID(containerID), state.failures)
	state.failures = 0
	state.lastWarn = time.Time{}
}

// logAttemptFailure keeps a persistent fault visible without letting a wedged
// daemon flood the log: the first failure warns, repeats drop to debug, and the
// warning resurfaces once per interval.
func (h *StatsHandler) logAttemptFailure(state *collectorState, containerID string, err error, backoff time.Duration) {
	if errors.Is(err, errStreamNotLive) {
		h.log.Debugf("Stats stream for %s is not live (container not running); retrying in %v", safeShortID(containerID), backoff)
		return
	}

	state.failures++
	now := h.now()
	if state.failures == 1 || now.Sub(state.lastWarn) >= h.warnInterval {
		state.lastWarn = now
		h.log.Warnf("Stats stream for %s failed (attempt %d, retrying in %v): %v",
			safeShortID(containerID), state.failures, backoff, err)
		return
	}
	h.log.Debugf("Stats stream for %s failed (attempt %d, retrying in %v): %v",
		safeShortID(containerID), state.failures, backoff, err)
}

// processStats processes raw Docker stats and sends to backend
func (h *StatsHandler) processStats(stat *container.StatsResponse, containerID, containerName string) {
	result := sharedDocker.CalculateStats(stat)

	now := time.Now().UTC().Format(time.RFC3339)
	cpuPct := sharedDocker.RoundToDecimal(result.CPUPercent, 1)
	memPct := sharedDocker.RoundToDecimal(result.MemoryPercent, 1)

	statsMsg := map[string]interface{}{
		"container_id":   containerID,
		"container_name": containerName,
		"cpu_percent":    cpuPct,
		"memory_usage":   result.MemoryUsage,
		"memory_limit":   result.MemoryLimit,
		"memory_percent": memPct,
		"network_rx":     result.NetworkRx,
		"network_tx":     result.NetworkTx,
		"disk_read":      result.DiskRead,
		"disk_write":     result.DiskWrite,
		"timestamp":      now,
	}

	if err := h.sendMessage("container_stats", statsMsg); err != nil {
		h.log.Errorf("Failed to send stats for %s: %v", safeShortID(containerID), err)
	}

	if ss := h.sender(); ss != nil {
		ss.Send(statsmsg.AgentStatsMsg{
			Type:          statsmsg.TypeContainerStats,
			ContainerID:   containerID,
			ContainerName: containerName,
			CPUPercent:    cpuPct,
			MemoryUsage:   result.MemoryUsage,
			MemoryLimit:   result.MemoryLimit,
			MemoryPercent: memPct,
			NetworkRx:     result.NetworkRx,
			NetworkTx:     result.NetworkTx,
			DiskRead:      result.DiskRead,
			DiskWrite:     result.DiskWrite,
			Timestamp:     now,
		})
	}
}
