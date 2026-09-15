package main

import (
	"errors"
	"log"
	"net/http"
	"strings"
	"sync"

	"github.com/darthnorse/dockmon-shared/hostdisk"
	"github.com/dockmon/stats-service/persistence"
	"github.com/gorilla/websocket"
)

// maxIngestMessageBytes bounds a single stats JSON message. A typical
// payload is well under 1KB; 16KB is generous head-room while preventing
// a misbehaving or malicious client from exhausting memory with a huge
// frame (gorilla/websocket's default is unlimited).
const maxIngestMessageBytes = 16 * 1024

// Message types on the ingest wire. An agent predating the typed format sends
// no type at all, which is treated as container stats.
const (
	msgTypeContainerStats = "container_stats"
	msgTypeHostStats      = "host_stats"
)

// dockerHostRegistry is the slice of StreamManager the ingest path needs to
// keep agent hosts and registered Docker hosts disjoint.
type dockerHostRegistry interface {
	HasHost(hostID string) bool
	RemoveDockerHost(hostID string)
}

// IngestHandler accepts WebSocket connections from agents and feeds the
// existing StatsCache. The host_id is bound from agent token validation
// at upgrade time, NEVER from the message body — so a compromised agent
// cannot spoof which host it belongs to. See spec §10.
type IngestHandler struct {
	db       *persistence.DB
	cache    *StatsCache
	upgrader websocket.Upgrader

	// hosts, when set, is consulted on connect so an agent taking over a
	// host_id evicts any surviving Docker registration for it.
	hosts dockerHostRegistry

	// sessions counts live ingest connections per host. A host with a live
	// session must not also be a registered Docker host, or the aggregator
	// and ingest would race on the same host cache key.
	sessionsMu sync.Mutex
	sessions   map[string]int
}

// agentStatsMsg is the wire format. Deliberately does NOT include host_id
// so a malicious client cannot smuggle it past the trusted-from-auth binding.
type agentStatsMsg struct {
	Type          string  `json:"type"`
	ContainerID   string  `json:"container_id"`
	ContainerName string  `json:"container_name"`
	CPUPercent    float64 `json:"cpu_percent"`
	MemoryUsage   uint64  `json:"memory_usage"`
	MemoryLimit   uint64  `json:"memory_limit"`
	MemoryPercent float64 `json:"memory_percent"`
	NetworkRx     uint64  `json:"network_rx"`
	NetworkTx     uint64  `json:"network_tx"`
	DiskRead      uint64  `json:"disk_read"`
	DiskWrite     uint64  `json:"disk_write"`

	// Host-stats fields (type == host_stats). Real /proc readings from the
	// agent, not container aggregates.
	MemoryUsedBytes  uint64 `json:"memory_used_bytes"`
	MemoryLimitBytes uint64 `json:"memory_limit_bytes"`

	// Host disk fields are pointers so presence is observable: an agent
	// that cannot measure disk omits them, and a genuine 0% still arrives.
	DiskPercent        *float64 `json:"disk_percent"`
	DiskUsedBytes      *uint64  `json:"disk_used_bytes"`
	DiskAvailableBytes *uint64  `json:"disk_available_bytes"`
	DiskTotalBytes     *uint64  `json:"disk_total_bytes"`
	DiskSource         *string  `json:"disk_source"`
}

// hostDisk returns the message's disk reading only when all five fields are
// present. A partial set is dropped: filling the gaps with zeros would turn
// it into a plausible measurement.
func (m *agentStatsMsg) hostDisk() *hostdisk.HostDisk {
	if m.DiskPercent == nil || m.DiskUsedBytes == nil || m.DiskAvailableBytes == nil ||
		m.DiskTotalBytes == nil || m.DiskSource == nil {
		return nil
	}
	return &hostdisk.HostDisk{
		DiskPercent:        *m.DiskPercent,
		DiskUsedBytes:      *m.DiskUsedBytes,
		DiskAvailableBytes: *m.DiskAvailableBytes,
		DiskTotalBytes:     *m.DiskTotalBytes,
		DiskSource:         *m.DiskSource,
	}
}

// HasActiveSession reports whether an agent currently holds an ingest
// connection for hostID.
func (h *IngestHandler) HasActiveSession(hostID string) bool {
	h.sessionsMu.Lock()
	defer h.sessionsMu.Unlock()
	return h.sessions[hostID] > 0
}

func (h *IngestHandler) openSession(hostID string) {
	h.sessionsMu.Lock()
	if h.sessions == nil {
		h.sessions = make(map[string]int)
	}
	h.sessions[hostID]++
	h.sessionsMu.Unlock()
}

func (h *IngestHandler) closeSession(hostID string) {
	h.sessionsMu.Lock()
	defer h.sessionsMu.Unlock()
	if h.sessions[hostID] <= 1 {
		delete(h.sessions, hostID)
		return
	}
	h.sessions[hostID]--
}

// HandleWebSocket authenticates the agent via its permanent UUID token,
// upgrades the HTTP connection to a WebSocket, and streams incoming stats
// messages into the StatsCache keyed by the authenticated host_id.
//
// Auth is intentionally NOT handled by authMiddleware (which uses the
// stats-service Bearer token); this endpoint validates per-connection
// against the agents table. See spec §10.
func (h *IngestHandler) HandleWebSocket(w http.ResponseWriter, r *http.Request) {
	token := extractAgentToken(r)
	if token == "" {
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}
	hostID, err := h.db.ValidateAgentToken(r.Context(), token)
	if err != nil {
		if errors.Is(err, persistence.ErrInvalidAgentToken) {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
		} else {
			log.Printf("Agent ingest: token validate error: %v", err)
			http.Error(w, "Internal error", http.StatusInternalServerError)
		}
		return
	}

	conn, err := h.upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("Agent ingest: upgrade failed: %v", err)
		return
	}
	defer conn.Close()

	h.openSession(hostID)
	defer h.closeSession(hostID)

	// An agent owns this host_id now. Any surviving Docker registration for
	// it would let the aggregator overwrite authenticated agent samples.
	if h.hosts != nil && h.hosts.HasHost(hostID) {
		log.Printf("Agent ingest: evicting stale Docker registration for host %s",
			truncateID(hostID, 8))
		h.hosts.RemoveDockerHost(hostID)
	}

	// Bound the per-message size so a single oversized frame cannot
	// exhaust memory. gorilla/websocket's default read limit is 0
	// (unlimited).
	conn.SetReadLimit(maxIngestMessageBytes)

	// ReadJSON blocks until a frame arrives or the connection is closed
	// by the peer; it does NOT observe r.Context(). To avoid leaking a
	// goroutine on server shutdown, spawn a watcher that closes the
	// connection when the request context is cancelled. Closing the
	// connection makes the in-flight ReadJSON return an error, which
	// drops us out of the loop and into the deferred conn.Close().
	ctx := r.Context()
	watcherDone := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
			_ = conn.Close()
		case <-watcherDone:
		}
	}()
	defer close(watcherDone)

	log.Printf("Agent ingest: connected for host %s", truncateID(hostID, 8))

	loggedUnknownType := false

	for {
		var msg agentStatsMsg
		if err := conn.ReadJSON(&msg); err != nil {
			log.Printf("Agent ingest: read error for host %s: %v",
				truncateID(hostID, 8), err)
			return
		}

		switch msg.Type {
		case msgTypeHostStats:
			// UpdateHostStats stamps LastUpdate internally.
			h.cache.UpdateHostStats(&HostStats{
				HostID:           hostID, // FROM AUTH, NOT MSG BODY
				CPUPercent:       msg.CPUPercent,
				MemoryPercent:    msg.MemoryPercent,
				MemoryUsedBytes:  msg.MemoryUsedBytes,
				MemoryLimitBytes: msg.MemoryLimitBytes,
				HostDisk:         msg.hostDisk(),
			})
		case "", msgTypeContainerStats:
			// Empty type is an agent predating the typed wire format.
			// Drop empty container IDs so we don't pollute the cache with
			// a blank composite key.
			if msg.ContainerID == "" {
				continue
			}
			// Normalize container ID at the boundary (CLAUDE.md defense-in-depth).
			// UpdateContainerStats sets LastUpdate internally.
			cid := msg.ContainerID
			if len(cid) > 12 {
				cid = cid[:12]
			}
			h.cache.UpdateContainerStats(&ContainerStats{
				ContainerID:   cid,
				ContainerName: msg.ContainerName,
				HostID:        hostID, // FROM AUTH, NOT MSG BODY
				CPUPercent:    msg.CPUPercent,
				MemoryUsage:   msg.MemoryUsage,
				MemoryLimit:   msg.MemoryLimit,
				MemoryPercent: msg.MemoryPercent,
				NetworkRx:     msg.NetworkRx,
				NetworkTx:     msg.NetworkTx,
				DiskRead:      msg.DiskRead,
				DiskWrite:     msg.DiskWrite,
			})
		default:
			// Once per connection, truncated: msg.Type is agent-controlled up
			// to the frame limit, and an unthrottled line here would let one
			// agent rotate the whole container log ring.
			if !loggedUnknownType {
				loggedUnknownType = true
				log.Printf("Agent ingest: unknown message type %q from host %s",
					truncateID(msg.Type, 32), truncateID(hostID, 8))
			}
		}
	}
}

// extractAgentToken pulls a Bearer token from the Authorization header or
// from the ?token= query parameter (some WebSocket clients can't set
// headers during the upgrade).
func extractAgentToken(r *http.Request) string {
	if h := r.Header.Get("Authorization"); strings.HasPrefix(h, "Bearer ") {
		return strings.TrimPrefix(h, "Bearer ")
	}
	return r.URL.Query().Get("token")
}
