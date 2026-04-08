package client

import (
	"context"
	"net/http"
	"strings"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/client/statsmsg"
	"github.com/gorilla/websocket"
	"github.com/sirupsen/logrus"
)

// AgentStatsMsg is the wire format for stats-service ingestion.
//
// The concrete type lives in the sibling `statsmsg` package so the agent's
// `handlers` package can reference it without creating an import cycle
// (`client` already imports `handlers`). This alias keeps `client.AgentStatsMsg`
// as the stable public name for callers inside this package.
type AgentStatsMsg = statsmsg.AgentStatsMsg

// StatsServiceClient maintains a WebSocket connection to stats-service's
// /api/stats/ws/ingest endpoint and ships AgentStatsMsg from a buffered
// channel. Drops on backpressure rather than blocking the producer.
type StatsServiceClient struct {
	url    string
	token  string
	log    *logrus.Logger
	sendCh chan AgentStatsMsg
}

// NewStatsServiceClient builds a client from a base backend URL (http/https)
// and the agent's permanent token (its agents.id row). The base URL scheme is
// rewritten to ws/wss and "/api/stats/ws/ingest" is appended.
func NewStatsServiceClient(backendURL, token string, log *logrus.Logger) *StatsServiceClient {
	wsURL := backendURL
	switch {
	case strings.HasPrefix(wsURL, "https://"):
		wsURL = "wss://" + strings.TrimPrefix(wsURL, "https://")
	case strings.HasPrefix(wsURL, "http://"):
		wsURL = "ws://" + strings.TrimPrefix(wsURL, "http://")
	}
	wsURL = strings.TrimRight(wsURL, "/") + "/api/stats/ws/ingest"
	return &StatsServiceClient{
		url:    wsURL,
		token:  token,
		log:    log,
		sendCh: make(chan AgentStatsMsg, 256),
	}
}

// Send enqueues a stats message; drops if the channel is full. Non-blocking.
func (c *StatsServiceClient) Send(msg AgentStatsMsg) {
	select {
	case c.sendCh <- msg:
	default:
		c.log.Warnf("Stats service channel full, dropping stats for %s", msg.ContainerID)
	}
}

// Run dials and pumps the channel until ctx is done. Reconnects with
// exponential backoff (1s → 30s cap) on connection errors.
func (c *StatsServiceClient) Run(ctx context.Context) {
	backoff := time.Second
	const maxBackoff = 30 * time.Second

	for {
		if ctx.Err() != nil {
			return
		}
		err := c.connectAndPump(ctx)
		if ctx.Err() != nil {
			return
		}
		c.log.Warnf("Stats service connection: %v; retrying in %v", err, backoff)
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		backoff *= 2
		if backoff > maxBackoff {
			backoff = maxBackoff
		}
	}
}

// connectAndPump opens a single WebSocket connection, drains sendCh into it,
// and returns when either the context is cancelled or a read/write fails.
// A background reader detects server-initiated closes even when the producer
// is idle, so reconnection can fire promptly.
func (c *StatsServiceClient) connectAndPump(ctx context.Context) error {
	header := http.Header{"Authorization": {"Bearer " + c.token}}
	conn, _, err := websocket.DefaultDialer.DialContext(ctx, c.url, header)
	if err != nil {
		return err
	}
	defer conn.Close()
	c.log.Info("Stats service connected")

	// Reader goroutine: the ingest endpoint is write-only from the agent's
	// perspective, but we still need to read so gorilla/websocket can process
	// control frames and surface a close error when the server disconnects.
	readErr := make(chan error, 1)
	go func() {
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				readErr <- err
				return
			}
		}
	}()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case err := <-readErr:
			return err
		case msg := <-c.sendCh:
			if err := conn.WriteJSON(msg); err != nil {
				return err
			}
		}
	}
}
