package client

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
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

	// Build WebSocket URL (convert http:// to ws:// and https:// to wss://)
	wsURL := c.cfg.DockMonURL
	if len(wsURL) > 7 && wsURL[:7] == "http://" {
		wsURL = "ws://" + wsURL[7:]
	} else if len(wsURL) > 8 && wsURL[:8] == "https://" {
		wsURL = "wss://" + wsURL[8:]
	}
	wsURL = wsURL + "/api/agent/ws"

	// Configure dialer with TLS settings
	dialer := websocket.DefaultDialer
	if c.cfg.InsecureSkipVerify {
		dialer.TLSClientConfig = &tls.Config{
			InsecureSkipVerify: true,
		}
		c.log.Warn("TLS certificate verification disabled (INSECURE_SKIP_VERIFY=true)")
	}

	// Connect
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

	// Collect system information (matches legacy host data structure)
	// This information is sent during registration to populate the DockerHost record
	c.log.Info("Collecting system information for registration")
	systemInfo, err := c.docker.GetSystemInfo(ctx)
	if err != nil {
		c.log.WithError(err).Warn("Failed to collect system info, continuing without it")
		systemInfo = nil
	} else if systemInfo != nil {
		c.log.WithFields(logrus.Fields{
			"hostname":       systemInfo.Hostname,
			"os_type":        systemInfo.OSType,
			"os_version":     systemInfo.OSVersion,
			"docker_version": systemInfo.DockerVersion,
			"total_memory":   systemInfo.TotalMemory,
			"num_cpus":       systemInfo.NumCPUs,
		}).Info("System information collected successfully")
	} else {
		c.log.Warn("GetSystemInfo returned nil without error")
	}

	// Determine hostname: prefer Docker host's hostname from systemInfo
	hostname := ""
	if systemInfo != nil && systemInfo.Hostname != "" {
		hostname = systemInfo.Hostname
	} else {
		// Fallback to container hostname (will be container ID)
		hostname, err = os.Hostname()
		if err != nil {
			c.log.WithError(err).Warn("Failed to get hostname, using engine ID")
			hostname = c.engineID[:12]
		}
	}

	// Build registration request as flat JSON (backend expects flat format)
	regMsg := map[string]interface{}{
		"type":          "register",
		"token":         token,
		"engine_id":     c.engineID,
		"hostname":      hostname,
		"version":       c.cfg.AgentVersion,
		"proto_version": c.cfg.ProtoVersion,
		"capabilities": map[string]bool{
			"container_operations": true,
			"container_updates":    true,
			"event_streaming":      true,
			"stats_collection":     true,
			"self_update":          c.myContainerID != "",
		},
	}

	// Add system information if available (aligns with DockerHostDB schema)
	if systemInfo != nil {
		regMsg["os_type"] = systemInfo.OSType
		regMsg["os_version"] = systemInfo.OSVersion
		regMsg["kernel_version"] = systemInfo.KernelVersion
		regMsg["docker_version"] = systemInfo.DockerVersion
		regMsg["daemon_started_at"] = systemInfo.DaemonStartedAt
		regMsg["total_memory"] = systemInfo.TotalMemory
		regMsg["num_cpus"] = systemInfo.NumCPUs
		c.log.Info("Added system information to registration message")
	} else {
		c.log.Warn("Skipping system information - systemInfo is nil")
	}

	// Send registration message as raw JSON
	data, err := json.Marshal(regMsg)
	if err != nil {
		return fmt.Errorf("failed to marshal registration: %w", err)
	}

	c.log.WithField("message", string(data)).Info("Sending registration message to backend")

	if err := c.conn.WriteMessage(websocket.TextMessage, data); err != nil {
		return fmt.Errorf("failed to send registration: %w", err)
	}

	// Wait for registration response
	c.conn.SetReadDeadline(time.Now().Add(10 * time.Second))
	defer c.conn.SetReadDeadline(time.Time{})

	_, respData, err := c.conn.ReadMessage()
	if err != nil {
		return fmt.Errorf("failed to read registration response: %w", err)
	}

	// Parse flat response from backend (not wrapped in Message envelope)
	var respMap map[string]interface{}
	if err := json.Unmarshal(respData, &respMap); err != nil {
		return fmt.Errorf("failed to decode registration response: %w", err)
	}

	// Check for error response
	if respType, ok := respMap["type"].(string); ok && respType == "auth_error" {
		if errMsg, ok := respMap["error"].(string); ok {
			return fmt.Errorf("registration rejected: %s", errMsg)
		}
		return fmt.Errorf("registration rejected: unknown error")
	}

	// Extract agent_id and host_id from flat response
	agentID, ok1 := respMap["agent_id"].(string)
	hostID, ok2 := respMap["host_id"].(string)
	if !ok1 || !ok2 {
		return fmt.Errorf("invalid registration response: missing agent_id or host_id")
	}

	// Store agent info
	c.agentID = agentID
	c.hostID = hostID
	c.registered = true

	// Check for permanent token and persist it
	if permanentToken, ok := respMap["permanent_token"].(string); ok && permanentToken != "" {
		c.cfg.PermanentToken = permanentToken

		// Persist token to disk with restricted permissions (0600 = owner read/write only)
		tokenPath := filepath.Join(c.cfg.DataPath, "permanent_token")
		if err := os.WriteFile(tokenPath, []byte(permanentToken), 0600); err != nil {
			c.log.WithError(err).Fatalf("CRITICAL: Failed to persist permanent token to %s - agent will lose identity on restart! Ensure volume is mounted: -v agent-data:/data", tokenPath)
		}
		c.log.WithField("path", tokenPath).Info("Permanent token persisted securely")
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

	// Handle new v2.2.0 container_operation messages
	if msg.Type == "container_operation" {
		c.handleContainerOperation(ctx, msg)
		return
	}

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

	case "get_system_info":
		// Return fresh system information (for periodic refresh)
		var sysInfo *docker.SystemInfo
		sysInfo, err = c.docker.GetSystemInfo(ctx)
		if err == nil {
			result = map[string]interface{}{
				"os_type":           sysInfo.OSType,
				"os_version":        sysInfo.OSVersion,
				"kernel_version":    sysInfo.KernelVersion,
				"docker_version":    sysInfo.DockerVersion,
				"daemon_started_at": sysInfo.DaemonStartedAt,
				"total_memory":      sysInfo.TotalMemory,
				"num_cpus":          sysInfo.NumCPUs,
			}
		}

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

// handleContainerOperation handles container operation messages (v2.2.0)
func (c *WebSocketClient) handleContainerOperation(ctx context.Context, msg *types.Message) {
	// Parse payload to extract operation parameters
	payload, ok := msg.Payload.(map[string]interface{})
	if !ok {
		c.log.Error("Invalid container_operation payload")
		return
	}

	action, _ := payload["action"].(string)
	containerID, _ := payload["container_id"].(string)
	correlationID, _ := payload["correlation_id"].(string)

	c.log.WithFields(logrus.Fields{
		"action":         action,
		"container_id":   containerID,
		"correlation_id": correlationID,
	}).Info("Handling container operation")

	// Execute operation
	var err error
	response := map[string]interface{}{
		"correlation_id": correlationID,
	}

	switch action {
	case "start":
		err = c.docker.StartContainer(ctx, containerID)
		if err == nil {
			response["success"] = true
			response["container_id"] = containerID
			response["status"] = "started"
		}

	case "stop":
		timeout := 10 // default
		if t, ok := payload["timeout"].(float64); ok {
			timeout = int(t)
		}
		err = c.docker.StopContainer(ctx, containerID, timeout)
		if err == nil {
			response["success"] = true
			response["container_id"] = containerID
			response["status"] = "stopped"
		}

	case "restart":
		timeout := 10 // default
		if t, ok := payload["timeout"].(float64); ok {
			timeout = int(t)
		}
		err = c.docker.RestartContainer(ctx, containerID, timeout)
		if err == nil {
			response["success"] = true
			response["container_id"] = containerID
			response["status"] = "restarted"
		}

	case "remove":
		force := false
		if f, ok := payload["force"].(bool); ok {
			force = f
		}
		err = c.docker.RemoveContainer(ctx, containerID, force)
		if err == nil {
			response["success"] = true
			response["container_id"] = containerID
			response["removed"] = true
		}

	case "get_logs":
		tail := "100" // default
		if t, ok := payload["tail"].(float64); ok {
			tail = fmt.Sprintf("%.0f", t)
		}
		var logs string
		logs, err = c.docker.GetContainerLogs(ctx, containerID, tail)
		if err == nil {
			response["success"] = true
			response["logs"] = logs
		}

	case "inspect":
		var containerJSON interface{}
		containerJSON, err = c.docker.InspectContainer(ctx, containerID)
		if err == nil {
			response["success"] = true
			response["container"] = containerJSON
		}

	default:
		err = fmt.Errorf("unknown action: %s", action)
	}

	// Add error to response if operation failed
	if err != nil {
		response["success"] = false
		response["error"] = err.Error()
		c.log.WithError(err).WithField("action", action).Error("Container operation failed")
	}

	// Send response with correlation_id
	if sendErr := c.sendJSON(response); sendErr != nil {
		c.log.WithError(sendErr).Error("Failed to send container operation response")
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

// sendJSON sends a raw JSON object directly (v2.2.0)
// Used for container operation responses with correlation_id
func (c *WebSocketClient) sendJSON(data interface{}) error {
	jsonData, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}

	c.connMu.Lock()
	defer c.connMu.Unlock()

	if c.conn == nil {
		return fmt.Errorf("connection not established")
	}

	if err := c.conn.WriteMessage(websocket.TextMessage, jsonData); err != nil {
		return fmt.Errorf("failed to write JSON message: %w", err)
	}

	return nil
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
