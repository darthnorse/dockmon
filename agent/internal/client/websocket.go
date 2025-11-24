package client

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/config"
	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/darthnorse/dockmon-agent/internal/handlers"
	"github.com/darthnorse/dockmon-agent/internal/protocol"
	"github.com/darthnorse/dockmon-agent/pkg/types"
	"github.com/gorilla/websocket"
	"github.com/sirupsen/logrus"
)

// WebSocketClient manages the WebSocket connection to DockMon
type WebSocketClient struct {
	cfg           *config.Config
	docker        *docker.Client
	engineID      string
	myContainerID string
	log           *logrus.Logger

	conn          *websocket.Conn
	connMu        sync.RWMutex
	registered    bool
	agentID       string
	hostID        string

	statsHandler      *handlers.StatsHandler
	updateHandler     *handlers.UpdateHandler
	selfUpdateHandler *handlers.SelfUpdateHandler

	stopChan      chan struct{}
	doneChan      chan struct{}
}

// NewWebSocketClient creates a new WebSocket client
func NewWebSocketClient(
	cfg *config.Config,
	dockerClient *docker.Client,
	engineID string,
	myContainerID string,
	log *logrus.Logger,
) *WebSocketClient {
	client := &WebSocketClient{
		cfg:           cfg,
		docker:        dockerClient,
		engineID:      engineID,
		myContainerID: myContainerID,
		log:           log,
		stopChan:      make(chan struct{}),
		doneChan:      make(chan struct{}),
	}

	// Initialize stats handler with sendEvent callback
	client.statsHandler = handlers.NewStatsHandler(
		dockerClient,
		log,
		client.sendEvent,
	)

	// Initialize update handler with sendEvent callback
	client.updateHandler = handlers.NewUpdateHandler(
		dockerClient,
		log,
		client.sendEvent,
	)

	// Initialize self-update handler with sendEvent callback
	client.selfUpdateHandler = handlers.NewSelfUpdateHandler(
		myContainerID,
		cfg.DataPath,
		log,
		client.sendEvent,
	)

	return client
}

// Run starts the WebSocket client with automatic reconnection
func (c *WebSocketClient) Run(ctx context.Context) error {
	defer close(c.doneChan)

	backoff := c.cfg.ReconnectInitial

	for {
		select {
		case <-ctx.Done():
			c.log.Info("Context cancelled, stopping client")
			return ctx.Err()
		case <-c.stopChan:
			c.log.Info("Stop signal received")
			return nil
		default:
		}

		// Attempt connection
		if err := c.connect(ctx); err != nil {
			c.log.WithError(err).Errorf("Connection failed, retrying in %v", backoff)

			// Wait before retry with exponential backoff
			select {
			case <-time.After(backoff):
				// Increase backoff (exponential)
				backoff = backoff * 2
				if backoff > c.cfg.ReconnectMax {
					backoff = c.cfg.ReconnectMax
				}
			case <-ctx.Done():
				return ctx.Err()
			case <-c.stopChan:
				return nil
			}
			continue
		}

		// Connection successful, reset backoff
		backoff = c.cfg.ReconnectInitial

		// Handle connection (blocks until disconnect)
		if err := c.handleConnection(ctx); err != nil {
			c.log.WithError(err).Warn("Connection handling error")
		}

		// Close connection
		c.closeConnection()
	}
}

// Stop stops the WebSocket client
func (c *WebSocketClient) Stop() {
	close(c.stopChan)
	<-c.doneChan
}

// connect establishes WebSocket connection and registers agent
func (c *WebSocketClient) connect(ctx context.Context) error {
	c.log.WithField("url", c.cfg.DockMonURL).Info("Connecting to DockMon")

	// Build WebSocket URL
	wsURL := c.cfg.DockMonURL + "/api/agent/ws"

	// Connect
	dialer := websocket.DefaultDialer
	conn, _, err := dialer.DialContext(ctx, wsURL, nil)
	if err != nil {
		return fmt.Errorf("failed to dial: %w", err)
	}

	c.connMu.Lock()
	c.conn = conn
	c.connMu.Unlock()

	// Send registration
	if err := c.register(ctx); err != nil {
		conn.Close()
		c.connMu.Lock()
		c.conn = nil
		c.connMu.Unlock()
		return fmt.Errorf("registration failed: %w", err)
	}

	c.log.WithFields(logrus.Fields{
		"agent_id": c.agentID,
		"host_id":  c.hostID,
	}).Info("Successfully registered with DockMon")

	return nil
}

// register sends registration message and waits for response
func (c *WebSocketClient) register(ctx context.Context) error {
	// Determine which token to use
	token := c.cfg.PermanentToken
	if token == "" {
		token = c.cfg.RegistrationToken
	}

	// Build registration request
	req := types.RegistrationRequest{
		Token:        token,
		EngineID:     c.engineID,
		Version:      c.cfg.AgentVersion,
		ProtoVersion: c.cfg.ProtoVersion,
		Capabilities: map[string]bool{
			"container_operations": true,
			"container_updates":    true,
			"event_streaming":      true,
			"stats_collection":     true,
			"self_update":          c.myContainerID != "",
		},
	}

	// Send registration message
	msg := &types.Message{
		Type:    "register",
		Payload: req,
	}

	if err := c.sendMessage(msg); err != nil {
		return fmt.Errorf("failed to send registration: %w", err)
	}

	// Wait for registration response
	c.conn.SetReadDeadline(time.Now().Add(10 * time.Second))
	defer c.conn.SetReadDeadline(time.Time{})

	_, data, err := c.conn.ReadMessage()
	if err != nil {
		return fmt.Errorf("failed to read registration response: %w", err)
	}

	respMsg, err := protocol.DecodeMessage(data)
	if err != nil {
		return fmt.Errorf("failed to decode registration response: %w", err)
	}

	if respMsg.Error != "" {
		return fmt.Errorf("registration rejected: %s", respMsg.Error)
	}

	// Parse registration response
	var resp types.RegistrationResponse
	if err := protocol.ParseCommand(respMsg, &resp); err != nil {
		return fmt.Errorf("failed to parse registration response: %w", err)
	}

	// Store agent info
	c.agentID = resp.AgentID
	c.hostID = resp.HostID
	c.registered = true

	// If we got a permanent token, we should store it
	// (In production, this would be persisted to disk)
	if resp.PermanentToken != "" {
		c.cfg.PermanentToken = resp.PermanentToken
		c.log.Info("Received permanent token (should be persisted)")
	}

	return nil
}

// handleConnection handles an active connection
func (c *WebSocketClient) handleConnection(ctx context.Context) error {
	// Start event streaming in background
	go c.streamEvents(ctx)

	// Start stats collection
	if err := c.statsHandler.StartStatsCollection(ctx); err != nil {
		c.log.WithError(err).Warn("Failed to start stats collection")
	} else {
		c.log.Info("Stats collection started")
	}

	// Ensure stats collection stops when we exit
	defer func() {
		c.statsHandler.StopAll()
		c.log.Info("Stats collection stopped")
	}()

	// Read messages in loop
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-c.stopChan:
			return nil
		default:
		}

		// Read message
		c.connMu.RLock()
		conn := c.conn
		c.connMu.RUnlock()

		if conn == nil {
			return fmt.Errorf("connection closed")
		}

		_, data, err := conn.ReadMessage()
		if err != nil {
			return fmt.Errorf("read error: %w", err)
		}

		// Decode message
		msg, err := protocol.DecodeMessage(data)
		if err != nil {
			c.log.WithError(err).Warn("Failed to decode message")
			continue
		}

		// Handle message
		go c.handleMessage(ctx, msg)
	}
}

// handleMessage handles a received message
func (c *WebSocketClient) handleMessage(ctx context.Context, msg *types.Message) {
	c.log.WithFields(logrus.Fields{
		"type":    msg.Type,
		"command": msg.Command,
		"id":      msg.ID,
	}).Debug("Received message")

	if msg.Type != "command" {
		c.log.WithField("type", msg.Type).Warn("Unexpected message type")
		return
	}

	// Dispatch command
	var result interface{}
	var err error

	switch msg.Command {
	case "ping":
		result = map[string]string{"status": "pong"}

	case "list_containers":
		result, err = c.docker.ListContainers(ctx)

	case "start_container":
		var op types.ContainerOperation
		if err = protocol.ParseCommand(msg, &op); err == nil {
			err = c.docker.StartContainer(ctx, op.ContainerID)
			result = map[string]string{"status": "started"}
		}

	case "stop_container":
		var op types.ContainerOperation
		if err = protocol.ParseCommand(msg, &op); err == nil {
			err = c.docker.StopContainer(ctx, op.ContainerID, 10)
			result = map[string]string{"status": "stopped"}
		}

	case "restart_container":
		var op types.ContainerOperation
		if err = protocol.ParseCommand(msg, &op); err == nil {
			err = c.docker.RestartContainer(ctx, op.ContainerID, 10)
			result = map[string]string{"status": "restarted"}
		}

	case "delete_container":
		var op types.ContainerOperation
		if err = protocol.ParseCommand(msg, &op); err == nil {
			err = c.docker.RemoveContainer(ctx, op.ContainerID, true)
			result = map[string]string{"status": "deleted"}
		}

	case "container_logs":
		var op types.ContainerOperation
		if err = protocol.ParseCommand(msg, &op); err == nil {
			var logs string
			logs, err = c.docker.GetContainerLogs(ctx, op.ContainerID, "100")
			result = map[string]string{"logs": logs}
		}

	case "update_container":
		var updateReq handlers.UpdateRequest
		if err = protocol.ParseCommand(msg, &updateReq); err == nil {
			// Run update in background and respond immediately
			go func() {
				if updateErr := c.updateHandler.UpdateContainer(ctx, updateReq); updateErr != nil {
					c.log.WithError(updateErr).Error("Container update failed")
				}
			}()
			result = map[string]string{"status": "update_started"}
		}

	case "self_update":
		var updateReq handlers.SelfUpdateRequest
		if err = protocol.ParseCommand(msg, &updateReq); err == nil {
			// Run self-update in background and respond immediately
			go func() {
				if updateErr := c.selfUpdateHandler.PerformSelfUpdate(ctx, updateReq); updateErr != nil {
					c.log.WithError(updateErr).Error("Self-update failed")
				} else {
					// Self-update prepared successfully, signal shutdown
					c.log.Info("Self-update prepared, shutting down for restart")
					// Give a moment for logs to flush
					time.Sleep(1 * time.Second)
					close(c.stopChan)
				}
			}()
			result = map[string]string{"status": "self_update_started"}
		}

	default:
		err = fmt.Errorf("unknown command: %s", msg.Command)
	}

	// Send response
	resp := protocol.NewCommandResponse(msg.ID, result, err)
	if sendErr := c.sendMessage(resp); sendErr != nil {
		c.log.WithError(sendErr).Error("Failed to send response")
	}
}

// streamEvents streams Docker events to DockMon
func (c *WebSocketClient) streamEvents(ctx context.Context) {
	c.log.Info("Starting event streaming")

	eventChan, errChan := c.docker.WatchEvents(ctx)

	for {
		select {
		case <-ctx.Done():
			return
		case <-c.stopChan:
			return
		case err := <-errChan:
			c.log.WithError(err).Error("Event stream error")
			return
		case event := <-eventChan:
			// Filter for container events
			if event.Type != "container" {
				continue
			}

			// Convert to our event type
			containerEvent := types.ContainerEvent{
				ContainerID:   event.Actor.ID,
				ContainerName: event.Actor.Attributes["name"],
				Image:         event.Actor.Attributes["image"],
				Action:        event.Action,
				Timestamp:     time.Unix(event.Time, 0),
				Attributes:    event.Actor.Attributes,
			}

			// Handle stats collection lifecycle based on container events
			switch event.Action {
			case "start":
				// Start stats collection for newly started container
				if err := c.statsHandler.StartContainerStats(ctx, event.Actor.ID, event.Actor.Attributes["name"]); err != nil {
					c.log.WithError(err).Warnf("Failed to start stats for container %s", event.Actor.ID[:12])
				}
			case "die", "stop", "kill":
				// Stop stats collection for stopped container
				c.statsHandler.StopContainerStats(event.Actor.ID)
			}

			// Send event
			eventMsg := protocol.NewEvent("container_event", containerEvent)
			if err := c.sendMessage(eventMsg); err != nil {
				c.log.WithError(err).Warn("Failed to send event")
			}
		}
	}
}

// sendMessage sends a message over WebSocket
func (c *WebSocketClient) sendMessage(msg *types.Message) error {
	data, err := protocol.EncodeMessage(msg)
	if err != nil {
		return fmt.Errorf("failed to encode message: %w", err)
	}

	c.connMu.Lock()
	defer c.connMu.Unlock()

	if c.conn == nil {
		return fmt.Errorf("connection not established")
	}

	if err := c.conn.WriteMessage(websocket.TextMessage, data); err != nil {
		return fmt.Errorf("failed to write message: %w", err)
	}

	return nil
}

// sendEvent is a helper that wraps sendMessage for event-style messages
// Used by handlers (e.g., stats handler) to send events
func (c *WebSocketClient) sendEvent(eventType string, payload interface{}) error {
	msg := protocol.NewEvent(eventType, payload)
	return c.sendMessage(msg)
}

// CheckPendingUpdate checks for and applies pending self-update
func (c *WebSocketClient) CheckPendingUpdate() error {
	return c.selfUpdateHandler.CheckAndApplyUpdate()
}

// closeConnection closes the WebSocket connection
func (c *WebSocketClient) closeConnection() {
	c.connMu.Lock()
	defer c.connMu.Unlock()

	if c.conn != nil {
		c.conn.Close()
		c.conn = nil
	}

	c.registered = false
}
