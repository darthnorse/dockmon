package main

import (
	"errors"
	"log"
	"net/http"
	"strings"

	"github.com/dockmon/stats-service/persistence"
	"github.com/gorilla/websocket"
)

// maxIngestMessageBytes bounds a single stats JSON message. A typical
// payload is well under 1KB; 16KB is generous head-room while preventing
// a misbehaving or malicious client from exhausting memory with a huge
// frame (gorilla/websocket's default is unlimited).
const maxIngestMessageBytes = 16 * 1024

// IngestHandler accepts WebSocket connections from agents and feeds the
// existing StatsCache. The host_id is bound from agent token validation
// at upgrade time, NEVER from the message body — so a compromised agent
// cannot spoof which host it belongs to. See spec §10.
type IngestHandler struct {
	db       *persistence.DB
	cache    *StatsCache
	upgrader websocket.Upgrader
}

// agentStatsMsg is the wire format. Deliberately does NOT include host_id
// so a malicious client cannot smuggle it past the trusted-from-auth binding.
type agentStatsMsg struct {
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

	for {
		var msg agentStatsMsg
		if err := conn.ReadJSON(&msg); err != nil {
			log.Printf("Agent ingest: read error for host %s: %v",
				truncateID(hostID, 8), err)
			return
		}
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
