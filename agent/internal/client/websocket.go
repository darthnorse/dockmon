package client

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
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

	statsHandler       *handlers.StatsHandler
	hostStatsHandler   *handlers.HostStatsHandler
	updateHandler      *handlers.UpdateHandler
	selfUpdateHandler  *handlers.SelfUpdateHandler
	healthCheckHandler *handlers.HealthCheckHandler
	deployHandler      *handlers.DeployHandler
	scanHandler        *handlers.ScanHandler
	shellHandler       *handlers.ShellHandler

	stopChan      chan struct{}
	doneChan      chan struct{}
	stopOnce      sync.Once  // Prevents double-close panic on stopChan

	// WaitGroup to track background goroutines (ping, event streaming)
	backgroundWg  sync.WaitGroup
	// WaitGroup to track message handler goroutines (must complete before backgroundWg.Wait)
	messageWg     sync.WaitGroup
}

// NewWebSocketClient creates a new WebSocket client
func NewWebSocketClient(
	ctx context.Context,
	cfg *config.Config,
	dockerClient *docker.Client,
	engineID string,
	myContainerID string,
	log *logrus.Logger,
) (*WebSocketClient, error) {
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

	// Initialize host stats handler for:
	// - Systemd agents: read directly from /proc
	// - Container agents with /host/proc mounted: read from /host/proc
	// This provides real host metrics instead of aggregating container stats
	if myContainerID == "" {
		// Systemd mode - always enable, reads from /proc
		client.hostStatsHandler = handlers.NewHostStatsHandler(
			log,
			client.sendJSON,
		)
		log.Info("Host stats handler initialized (systemd mode)")
	} else if _, err := os.Stat("/host/proc/stat"); err == nil {
		// Container mode with /host/proc mounted - enable host stats
		client.hostStatsHandler = handlers.NewHostStatsHandler(
			log,
			client.sendJSON,
		)
		log.Info("Host stats handler initialized (container mode with /host/proc mount)")
	}

	// Initialize update handler with sendEvent callback
	client.updateHandler = handlers.NewUpdateHandler(
		dockerClient,
		log,
		client.sendEvent,
	)

	// Initialize self-update handler with sendEvent callback
	// Pass docker client for container mode and signalStop for graceful shutdown
	client.selfUpdateHandler = handlers.NewSelfUpdateHandler(
		myContainerID,
		cfg.DataPath,
		log,
		client.sendEvent,
		dockerClient,
		client.signalStop,
	)

	// Initialize health check handler with sendEvent callback
	client.healthCheckHandler = handlers.NewHealthCheckHandler(
		log,
		client.sendEvent,
	)

	// Initialize deploy handler with sendEvent callback
	// Note: This may fail if Docker Compose is not installed, which is OK
	var err error
	client.deployHandler, err = handlers.NewDeployHandler(
		ctx,
		dockerClient,
		log,
		client.sendEvent,
	)
	if err != nil {
		log.WithError(err).Warn("Deploy handler not available (Docker Compose not installed)")
		// Continue without deploy support - not a fatal error
	} else {
		log.WithField("compose_cmd", client.deployHandler.GetComposeCommand()).Info("Deploy handler initialized")
	}

	// Initialize scan handler for directory scanning
	client.scanHandler = handlers.NewScanHandler(log, client.sendEvent)
	log.Info("Scan handler initialized")

	// Initialize shell handler for interactive container shell access
	client.shellHandler = handlers.NewShellHandler(dockerClient, log, client.sendEvent)
	log.Info("Shell handler initialized")

	return client, nil
}

// Run starts the WebSocket client with automatic reconnection
func (c *WebSocketClient) Run(ctx context.Context) error {
	defer close(c.doneChan)

	backoff := c.cfg.ReconnectInitial
	isReconnect := false

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

		// Log reconnection attempts clearly
		if isReconnect {
			c.log.WithField("backoff", backoff).Info("Attempting to reconnect to DockMon...")
		}

		// Attempt connection
		if err := c.connect(ctx); err != nil {
			c.log.WithField("error", err.Error()).Errorf("Connection failed, retrying in %v", backoff)

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
			isReconnect = true
			continue
		}

		// Connection successful, reset backoff
		backoff = c.cfg.ReconnectInitial
		isReconnect = false

		// Handle connection (blocks until disconnect)
		if err := c.handleConnection(ctx); err != nil {
			c.log.WithError(err).Warn("Connection lost, will attempt to reconnect")
		}

		// Close connection and prepare for reconnect
		c.closeConnection()
		isReconnect = true
	}
}

// Stop stops the WebSocket client
func (c *WebSocketClient) Stop() {
	c.signalStop()
	<-c.doneChan
}

// signalStop safely closes stopChan exactly once (prevents panic on double-close)
func (c *WebSocketClient) signalStop() {
	c.stopOnce.Do(func() {
		close(c.stopChan)
	})
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
			// Safe slice: use full ID if shorter than 12 chars
			hostname = c.engineID
			if len(hostname) > 12 {
				hostname = hostname[:12]
			}
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
			"compose_deployments":  c.deployHandler != nil,
			"shell_access":         true,
		},
	}

	// Add agent runtime info (GOOS/GOARCH) - needed for binary downloads
	regMsg["agent_os"] = runtime.GOOS     // linux, darwin, windows
	regMsg["agent_arch"] = runtime.GOARCH // amd64, arm64, arm

	// Add system information if available (aligns with DockerHostDB schema)
	if systemInfo != nil {
		regMsg["os_type"] = systemInfo.OSType
		regMsg["os_version"] = systemInfo.OSVersion
		regMsg["kernel_version"] = systemInfo.KernelVersion
		regMsg["docker_version"] = systemInfo.DockerVersion
		regMsg["daemon_started_at"] = systemInfo.DaemonStartedAt
		regMsg["total_memory"] = systemInfo.TotalMemory
		regMsg["num_cpus"] = systemInfo.NumCPUs

		// Only include host_ip for systemd agents (not running in a container)
		// Container agents would report Docker network IPs which aren't useful
		if c.myContainerID == "" && systemInfo.HostIP != "" {
			regMsg["host_ip"] = systemInfo.HostIP
			c.log.WithField("host_ip", systemInfo.HostIP).Info("Added host IP to registration (systemd mode)")
		}

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

	// Set write deadline for registration message
	c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	err = c.conn.WriteMessage(websocket.TextMessage, data)
	c.conn.SetWriteDeadline(time.Time{})  // Clear deadline

	if err != nil {
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
	// Create connection-scoped context that we cancel when disconnecting
	// This ensures background goroutines (event streaming) stop when connection drops
	connCtx, connCancel := context.WithCancel(ctx)
	defer connCancel() // Ensure context is cancelled on any exit path

	// Configure ping/pong for connection health monitoring
	// This detects stale connections (NAT timeout, firewall changes, network partitions)
	const (
		pingInterval = 30 * time.Second  // Send ping every 30s
		pongTimeout  = 10 * time.Second  // Expect pong within 10s
	)

	c.connMu.RLock()
	conn := c.conn
	c.connMu.RUnlock()

	if conn == nil {
		return fmt.Errorf("connection not established")
	}

	// Set up pong handler - resets read deadline when pong received
	conn.SetPongHandler(func(appData string) error {
		c.log.Debug("Received pong from server")
		// Extend read deadline on pong
		return conn.SetReadDeadline(time.Now().Add(pingInterval + pongTimeout))
	})

	// Set initial read deadline
	conn.SetReadDeadline(time.Now().Add(pingInterval + pongTimeout))

	// Start shutdown watcher goroutine - closes connection when stop is signaled
	// This makes shutdown responsive instead of waiting for read deadline (up to 40s)
	c.backgroundWg.Add(1)
	go func() {
		defer func() {
			c.log.Info("Goroutine exit: shutdown watcher")
			c.backgroundWg.Done()
		}()
		select {
		case <-connCtx.Done():
			return
		case <-c.stopChan:
			c.log.Debug("Stop signal received, closing connection to interrupt read")
			c.connMu.Lock()
			if c.conn != nil {
				c.conn.Close()
				c.conn = nil  // Set to nil so other goroutines detect closure
			}
			c.connMu.Unlock()
		}
	}()

	// Start ping goroutine to keep connection alive and detect stale connections
	c.backgroundWg.Add(1)
	go func() {
		defer func() {
			c.log.Info("Goroutine exit: ping")
			c.backgroundWg.Done()
		}()
		ticker := time.NewTicker(pingInterval)
		defer ticker.Stop()

		for {
			select {
			case <-connCtx.Done():
				return
			case <-c.stopChan:
				return
			case <-ticker.C:
				// Must hold WRITE lock for WebSocket writes (gorilla allows only 1 concurrent writer)
				c.connMu.Lock()
				if c.conn == nil {
					c.connMu.Unlock()
					return
				}

				// Send ping with write deadline
				c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
				err := c.conn.WriteMessage(websocket.PingMessage, nil)
				c.conn.SetWriteDeadline(time.Time{})  // Clear write deadline
				c.connMu.Unlock()

				if err != nil {
					c.log.WithError(err).Warn("Failed to send ping")
					return
				}
				c.log.Debug("Sent ping to server")
			}
		}
	}()

	// Start event streaming in background with WaitGroup tracking
	c.backgroundWg.Add(1)
	go func() {
		defer func() {
			c.log.Info("Goroutine exit: event streaming")
			c.backgroundWg.Done()
		}()
		c.streamEvents(connCtx)
	}()

	// Start stats collection
	if err := c.statsHandler.StartStatsCollection(connCtx); err != nil {
		c.log.WithError(err).Warn("Failed to start stats collection")
	} else {
		c.log.Info("Stats collection started")
	}

	// Start host stats collection for systemd agents
	if c.hostStatsHandler != nil {
		c.backgroundWg.Add(1)
		go func() {
			defer c.backgroundWg.Done()
			c.hostStatsHandler.StartCollection(connCtx, 2*time.Second)
		}()
		c.log.Info("Host stats collection started (systemd mode)")
	}

	// Start health check handler
	c.healthCheckHandler.Start(connCtx)
	c.log.Info("Health check handler started")

	// Ensure cleanup when we exit
	// IMPORTANT: Order matters here to prevent deadlocks and races:
	// 1. Cancel context to signal goroutines to stop
	// 2. Wait for message handlers (which may call backgroundWg.Add)
	// 3. Wait for background goroutines (ping, events, updates)
	defer func() {
		// Cancel context first to signal event streaming and ping goroutines to stop
		c.log.Info("Connection cleanup: cancelling context")
		connCancel()

		c.statsHandler.StopAll()
		c.log.Info("Connection cleanup: stats stopped")

		c.healthCheckHandler.Stop()
		c.log.Info("Connection cleanup: health checks stopped")

		c.shellHandler.CloseAll()
		c.log.Info("Connection cleanup: shell sessions closed")

		// Wait for message handlers first - they may call backgroundWg.Add()
		// This prevents the race: backgroundWg.Add() called after Wait() returns
		c.log.Info("Connection cleanup: waiting for message handlers")
		c.messageWg.Wait()
		c.log.Info("Connection cleanup: message handlers done")

		// Now safe to wait for background goroutines (all Add() calls have completed)
		c.log.Info("Connection cleanup: waiting for background goroutines")
		c.backgroundWg.Wait()
		c.log.Info("Connection cleanup: all goroutines stopped")
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

		// Read message (will timeout based on read deadline set by pong handler)
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

		// Reset read deadline after successful read
		conn.SetReadDeadline(time.Now().Add(pingInterval + pongTimeout))

		// Decode message
		msg, err := protocol.DecodeMessage(data)
		if err != nil {
			c.log.WithError(err).Warn("Failed to decode message")
			continue
		}

		// Handle message in goroutine, tracked by messageWg
		// This ensures all Add() calls to backgroundWg happen before backgroundWg.Wait()
		c.messageWg.Add(1)
		go func(m *types.Message) {
			defer c.messageWg.Done()
			c.handleMessage(ctx, m)
		}(msg)
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

	// Handle health check config messages
	if msg.Type == "health_check_config" {
		c.handleHealthCheckConfig(msg)
		return
	}

	if msg.Type == "health_check_configs_sync" {
		c.handleHealthCheckConfigsSync(msg)
		return
	}

	if msg.Type == "health_check_config_remove" {
		c.handleHealthCheckConfigRemove(msg)
		return
	}

	// Handle shell session commands
	if msg.Type == "shell_session" {
		c.handleShellSession(ctx, msg)
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
	case "list_containers":
		result, err = c.docker.ListContainers(ctx)

	case "update_container":
		var updateReq handlers.UpdateRequest
		if err = protocol.ParseCommand(msg, &updateReq); err == nil {
			// Run update in background and respond immediately
			// Use background context so update continues even if WebSocket disconnects
			c.backgroundWg.Add(1)
			go func() {
				defer c.backgroundWg.Done()
				// Use background context instead of connection context
				// This allows updates to complete even if connection drops
				updateCtx := context.Background()
				updateResult, updateErr := c.updateHandler.UpdateContainer(updateCtx, updateReq)
				if updateErr != nil {
					c.log.WithError(updateErr).Error("Container update failed")
				} else {
					c.log.WithFields(logrus.Fields{
						"old_container": updateResult.OldContainerID,
						"new_container": updateResult.NewContainerID,
						"name":          updateResult.ContainerName,
					}).Info("Container update completed")
				}
			}()
			result = map[string]string{"status": "update_started"}
		}

	case "self_update":
		var updateReq handlers.SelfUpdateRequest
		if err = protocol.ParseCommand(msg, &updateReq); err == nil {
			// Run self-update in background and respond immediately
			// Use background context so update continues even if WebSocket disconnects
			c.backgroundWg.Add(1)
			go func() {
				defer c.backgroundWg.Done()
				// Use background context for self-update
				updateCtx := context.Background()
				if updateErr := c.selfUpdateHandler.PerformSelfUpdate(updateCtx, updateReq); updateErr != nil {
					c.log.WithError(updateErr).Error("Self-update failed")
				} else {
					// Self-update prepared successfully, signal shutdown
					c.log.Info("Self-update prepared, shutting down for restart")
					// Give a moment for logs to flush
					time.Sleep(1 * time.Second)
					c.signalStop()  // Use safe stop to prevent double-close panic
				}
			}()
			result = map[string]string{"status": "self_update_started"}
		}

	case "deploy_compose":
		if c.deployHandler == nil {
			err = fmt.Errorf("compose deployments not available on this agent")
		} else {
			var deployReq handlers.DeployComposeRequest
			if err = protocol.ParseCommand(msg, &deployReq); err == nil {
				// Run deployment in background and respond immediately
				// Use background context so deployment continues even if WebSocket disconnects
				c.backgroundWg.Add(1)
				go func() {
					defer c.backgroundWg.Done()
					// Use background context for deployment
					deployCtx := context.Background()
					deployResult := c.deployHandler.DeployCompose(deployCtx, deployReq)

					// Send completion event with result
					if sendErr := c.sendEvent("deploy_complete", deployResult); sendErr != nil {
						c.log.WithError(sendErr).Error("Failed to send deploy_complete event")
					}
				}()
				result = map[string]string{"status": "deployment_started"}
			}
		}

	case "scan_compose_dirs":
		var scanReq handlers.ScanComposeDirsRequest
		if err = protocol.ParseCommand(msg, &scanReq); err == nil {
			// Run scan synchronously (it's fast) and return result
			scanResult := c.scanHandler.ScanComposeDirs(ctx, scanReq)
			result = scanResult
		}

	case "read_compose_file":
		var readReq handlers.ReadComposeFileRequest
		if err = protocol.ParseCommand(msg, &readReq); err == nil {
			// Run read synchronously (it's fast) and return result
			readResult := c.scanHandler.ReadComposeFile(ctx, readReq)
			result = readResult
		}

	case "list_images":
		// List all images with usage information
		result, err = c.docker.ListImages(ctx)

	case "remove_image":
		// Remove a Docker image
		var removeReq struct {
			ImageID string `json:"image_id"`
			Force   bool   `json:"force"`
		}
		if err = protocol.ParseCommand(msg, &removeReq); err == nil {
			err = c.docker.RemoveImage(ctx, removeReq.ImageID, removeReq.Force)
			if err == nil {
				result = map[string]bool{"success": true}
			}
		}

	case "prune_images":
		// Prune all unused images
		result, err = c.docker.PruneImages(ctx)

	case "list_networks":
		// List all networks with connected container info
		result, err = c.docker.ListNetworks(ctx)

	case "delete_network":
		// Delete a Docker network
		var deleteReq struct {
			NetworkID string `json:"network_id"`
			Force     bool   `json:"force"`
		}
		if err = protocol.ParseCommand(msg, &deleteReq); err == nil {
			err = c.docker.DeleteNetwork(ctx, deleteReq.NetworkID, deleteReq.Force)
			if err == nil {
				result = map[string]bool{"success": true}
			}
		}

	case "prune_networks":
		// Prune all unused networks
		result, err = c.docker.PruneNetworks(ctx)

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
	// Correlation ID is in msg.ID (Message struct), not in payload
	correlationID := msg.ID

	// Log read-only operations at DEBUG level (high frequency), state-changing at INFO
	logEntry := c.log.WithFields(logrus.Fields{
		"action":         action,
		"container_id":   containerID,
		"correlation_id": correlationID,
	})
	if action == "get_logs" || action == "inspect" {
		logEntry.Debug("Handling container operation")
	} else {
		logEntry.Info("Handling container operation")
	}

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
			c.log.Info("Event streaming: context cancelled")
			return
		case <-c.stopChan:
			c.log.Info("Event streaming: stop signal received")
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
			action := string(event.Action) // Convert typed Action to string
			containerEvent := types.ContainerEvent{
				ContainerID:   event.Actor.ID,
				ContainerName: event.Actor.Attributes["name"],
				Image:         event.Actor.Attributes["image"],
				Action:        action,
				Timestamp:     time.Unix(event.Time, 0),
				Attributes:    event.Actor.Attributes,
			}

			// Handle stats collection lifecycle based on container events
			switch action {
			case "start":
				// Start stats collection for newly started container
				if err := c.statsHandler.StartContainerStats(ctx, event.Actor.ID, event.Actor.Attributes["name"]); err != nil {
					// Safe slice: use full ID if shorter than 12 chars
					shortID := event.Actor.ID
					if len(shortID) > 12 {
						shortID = shortID[:12]
					}
					c.log.WithError(err).Warnf("Failed to start stats for container %s", shortID)
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

	// Set write deadline to prevent blocking indefinitely on slow/congested networks
	c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	err = c.conn.WriteMessage(websocket.TextMessage, data)
	c.conn.SetWriteDeadline(time.Time{})  // Clear deadline

	if err != nil {
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

	// Set write deadline to prevent blocking indefinitely on slow/congested networks
	c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	err = c.conn.WriteMessage(websocket.TextMessage, jsonData)
	c.conn.SetWriteDeadline(time.Time{})  // Clear deadline

	if err != nil {
		return fmt.Errorf("failed to write JSON message: %w", err)
	}

	return nil
}

// CheckPendingUpdate checks for and applies pending self-update
func (c *WebSocketClient) CheckPendingUpdate() error {
	return c.selfUpdateHandler.CheckAndApplyUpdate()
}

// handleHealthCheckConfig handles a single health check config update
func (c *WebSocketClient) handleHealthCheckConfig(msg *types.Message) {
	payload, ok := msg.Payload.(map[string]interface{})
	if !ok {
		c.log.Error("Invalid health_check_config payload")
		return
	}

	// Parse config from payload
	config := c.parseHealthCheckConfig(payload)
	if config == nil {
		return
	}

	c.healthCheckHandler.UpdateConfig(config)
	c.log.WithFields(logrus.Fields{
		"container_id": config.ContainerID,
		"enabled":      config.Enabled,
	}).Info("Health check config updated")
}

// handleHealthCheckConfigsSync handles sync of all health check configs
func (c *WebSocketClient) handleHealthCheckConfigsSync(msg *types.Message) {
	payload, ok := msg.Payload.(map[string]interface{})
	if !ok {
		c.log.Error("Invalid health_check_configs_sync payload")
		return
	}

	configsRaw, ok := payload["configs"].([]interface{})
	if !ok {
		c.log.Error("Missing configs array in health_check_configs_sync")
		return
	}

	var configs []handlers.HealthCheckConfig
	for _, configRaw := range configsRaw {
		configMap, ok := configRaw.(map[string]interface{})
		if !ok {
			continue
		}

		config := c.parseHealthCheckConfig(configMap)
		if config != nil {
			configs = append(configs, *config)
		}
	}

	c.healthCheckHandler.SyncConfigs(configs)
	c.log.WithField("count", len(configs)).Info("Health check configs synced")
}

// handleHealthCheckConfigRemove handles removal of a health check config
func (c *WebSocketClient) handleHealthCheckConfigRemove(msg *types.Message) {
	payload, ok := msg.Payload.(map[string]interface{})
	if !ok {
		c.log.Error("Invalid health_check_config_remove payload")
		return
	}

	containerID, ok := payload["container_id"].(string)
	if !ok || containerID == "" {
		c.log.Error("Missing container_id in health_check_config_remove")
		return
	}

	c.healthCheckHandler.RemoveConfig(containerID)
	c.log.WithField("container_id", containerID).Info("Health check config removed")
}

// parseHealthCheckConfig parses a health check config from a map
func (c *WebSocketClient) parseHealthCheckConfig(data map[string]interface{}) *handlers.HealthCheckConfig {
	containerID, _ := data["container_id"].(string)
	if containerID == "" {
		c.log.Error("Missing container_id in health check config")
		return nil
	}

	config := &handlers.HealthCheckConfig{
		ContainerID: containerID,
	}

	// Parse optional fields
	if v, ok := data["host_id"].(string); ok {
		config.HostID = v
	}
	if v, ok := data["enabled"].(bool); ok {
		config.Enabled = v
	}
	if v, ok := data["url"].(string); ok {
		config.URL = v
	}
	if v, ok := data["method"].(string); ok {
		config.Method = v
	}
	if v, ok := data["expected_status_codes"].(string); ok {
		config.ExpectedStatusCodes = v
	}
	if v, ok := data["timeout_seconds"].(float64); ok {
		config.TimeoutSeconds = int(v)
	}
	if v, ok := data["check_interval_seconds"].(float64); ok {
		config.CheckIntervalSeconds = int(v)
	}
	if v, ok := data["follow_redirects"].(bool); ok {
		config.FollowRedirects = v
	}
	if v, ok := data["verify_ssl"].(bool); ok {
		config.VerifySSL = v
	}
	if v, ok := data["headers_json"].(string); ok {
		config.HeadersJSON = v
	}
	if v, ok := data["auth_config_json"].(string); ok {
		config.AuthConfigJSON = v
	}

	return config
}

// handleShellSession handles shell session commands from the backend
func (c *WebSocketClient) handleShellSession(ctx context.Context, msg *types.Message) {
	payload, ok := msg.Payload.(map[string]interface{})
	if !ok {
		c.log.Error("Invalid shell_session payload")
		return
	}

	cmd := types.ShellSessionCommand{
		Action:      getString(payload, "action"),
		ContainerID: getString(payload, "container_id"),
		SessionID:   getString(payload, "session_id"),
		Data:        getString(payload, "data"),
	}

	if cols, ok := payload["cols"].(float64); ok {
		cmd.Cols = int(cols)
	}
	if rows, ok := payload["rows"].(float64); ok {
		cmd.Rows = int(rows)
	}

	c.log.WithFields(logrus.Fields{
		"action":     cmd.Action,
		"session_id": cmd.SessionID,
	}).Debug("Handling shell session command")

	c.shellHandler.HandleCommand(ctx, cmd)
}

// getString safely extracts a string from a map
func getString(m map[string]interface{}, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

// closeConnection closes the WebSocket connection
func (c *WebSocketClient) closeConnection() {
	// Close connection under lock (quick operation)
	c.connMu.Lock()
	if c.conn != nil {
		c.conn.Close()
		c.conn = nil
	}
	c.connMu.Unlock()  // Release lock BEFORE waiting

	// Wait for background goroutines to complete (with timeout)
	// This is done WITHOUT holding the lock to prevent blocking other goroutines
	done := make(chan struct{})
	go func() {
		c.backgroundWg.Wait()
		close(done)
	}()

	select {
	case <-done:
		c.log.Info("All background operations completed")
	case <-time.After(30 * time.Second):
		c.log.Warn("Timed out waiting for background operations to complete")
	}

	c.registered = false
}
