package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"os"
	"time"

	"github.com/darthnorse/dockmon-shared/compose"
	sharedDocker "github.com/darthnorse/dockmon-shared/docker"
	"github.com/darthnorse/dockmon-shared/update"
	"github.com/docker/docker/client"
	"github.com/dockmon/compose-service/internal/metrics"
	"github.com/sirupsen/logrus"
)

const (
	// DefaultSocketPath is the default Unix socket path
	DefaultSocketPath = "/tmp/compose.sock"
	// DefaultHealthTimeout is the timeout for health checks in seconds
	DefaultHealthTimeout = 2
)

// Server represents the compose HTTP server
type Server struct {
	socketPath  string
	log         *logrus.Logger
	startTime   time.Time
	initialized bool
	listener    net.Listener
	httpServer  *http.Server
}

// NewServer creates a new compose server
func NewServer(socketPath string, log *logrus.Logger) *Server {
	if socketPath == "" {
		socketPath = DefaultSocketPath
	}

	return &Server{
		socketPath:  socketPath,
		log:         log,
		startTime:   time.Now(),
		initialized: true,
	}
}

// Start starts the HTTP server on the Unix socket
func (s *Server) Start(ctx context.Context) error {
	// Clean up stale temp files from previous crashes
	compose.CleanupStaleFiles(s.log)

	// Remove existing socket file if it exists
	if err := os.Remove(s.socketPath); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to remove existing socket: %w", err)
	}

	// Create Unix socket listener
	listener, err := net.Listen("unix", s.socketPath)
	if err != nil {
		return fmt.Errorf("failed to listen on socket: %w", err)
	}
	s.listener = listener

	// Set socket permissions (owner read/write, group read/write)
	if err := os.Chmod(s.socketPath, 0660); err != nil {
		listener.Close()
		return fmt.Errorf("failed to set socket permissions: %w", err)
	}

	// Create HTTP server with routes
	mux := http.NewServeMux()
	mux.HandleFunc("/health", s.handleHealth)
	mux.HandleFunc("/deploy", s.handleDeploy)
	mux.HandleFunc("/update", s.handleUpdate)

	s.httpServer = &http.Server{
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 0, // Disabled for SSE streaming
		IdleTimeout:  120 * time.Second,
	}

	s.log.WithField("socket", s.socketPath).Info("Compose service starting")

	// Handle graceful shutdown
	go func() {
		<-ctx.Done()
		s.log.Info("Shutting down compose service...")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		s.httpServer.Shutdown(shutdownCtx)
	}()

	// Start serving (blocks until shutdown)
	if err := s.httpServer.Serve(listener); err != http.ErrServerClosed {
		return fmt.Errorf("server error: %w", err)
	}

	return nil
}

// Stop stops the server
func (s *Server) Stop() error {
	if s.httpServer != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		return s.httpServer.Shutdown(ctx)
	}
	return nil
}

// HealthResponse represents the health check response
type HealthResponse struct {
	Status       string                 `json:"status"`          // "ok" or "degraded"
	DockerOK     bool                   `json:"docker_ok"`       // Can connect to local Docker
	ComposeReady bool                   `json:"compose_ready"`   // Compose SDK initialized
	UptimeSecs   int64                  `json:"uptime_secs"`     // Seconds since startup
	Metrics      map[string]interface{} `json:"metrics,omitempty"` // Deployment stats
}

// handleHealth handles the /health endpoint
func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	resp := HealthResponse{
		Status:       "ok",
		UptimeSecs:   int64(time.Since(s.startTime).Seconds()),
		ComposeReady: s.initialized,
	}

	// Quick Docker ping (timeout 2s)
	ctx, cancel := context.WithTimeout(r.Context(), DefaultHealthTimeout*time.Second)
	defer cancel()

	localClient, err := sharedDocker.CreateLocalClient()
	if err != nil {
		resp.Status = "degraded"
		resp.DockerOK = false
	} else {
		defer localClient.Close()
		_, err = localClient.Ping(ctx)
		resp.DockerOK = (err == nil)
		if !resp.DockerOK {
			resp.Status = "degraded"
		}
	}

	// Include metrics
	resp.Metrics = metrics.Global.Snapshot()

	w.Header().Set("Content-Type", "application/json")
	if resp.Status != "ok" {
		w.WriteHeader(http.StatusServiceUnavailable)
	}
	json.NewEncoder(w).Encode(resp)
}

// handleDeploy handles the /deploy endpoint with SSE streaming
func (s *Server) handleDeploy(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Parse request
	var req compose.DeployRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, fmt.Sprintf("Invalid request: %v", err), http.StatusBadRequest)
		return
	}

	// Validate required fields
	if req.DeploymentID == "" || req.ProjectName == "" || req.ComposeYAML == "" {
		http.Error(w, "Missing required fields: deployment_id, project_name, compose_yaml", http.StatusBadRequest)
		return
	}

	// Check if client wants SSE
	acceptHeader := r.Header.Get("Accept")
	useSSE := acceptHeader == "text/event-stream"

	if useSSE {
		s.handleDeploySSE(w, r, req)
	} else {
		s.handleDeployJSON(w, r, req)
	}
}

// handleDeployJSON handles deployment with JSON response (no streaming)
func (s *Server) handleDeployJSON(w http.ResponseWriter, r *http.Request, req compose.DeployRequest) {
	startTime := time.Now()
	metrics.Global.IncrementActive()
	defer metrics.Global.DecrementActive()

	s.log.WithFields(logrus.Fields{
		"deployment_id": req.DeploymentID,
		"project_name":  req.ProjectName,
		"action":        req.Action,
		"host_type":     compose.GetHostType(req),
	}).Info("Deployment started")

	// Create Docker client
	dockerClient, err := s.createDockerClient(req)
	if err != nil {
		s.log.WithError(err).Error("Failed to create Docker client")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(compose.DeployResult{
			DeploymentID: req.DeploymentID,
			Success:      false,
			Error:        compose.NewDockerError(err.Error()),
		})
		return
	}
	defer dockerClient.Close()

	// Create compose service
	svc := compose.NewService(dockerClient, s.log)

	// Execute deployment
	result := svc.Deploy(r.Context(), req)

	// Record metrics
	duration := time.Since(startTime)
	metrics.Global.RecordDeployment(result.Success, result.PartialSuccess, duration)

	s.log.WithFields(logrus.Fields{
		"deployment_id":   req.DeploymentID,
		"success":         result.Success,
		"partial_success": result.PartialSuccess,
		"duration_secs":   duration.Seconds(),
		"service_count":   len(result.Services),
		"failed_count":    len(result.FailedServices),
	}).Info("Deployment completed")

	// Return result
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

// handleDeploySSE handles deployment with SSE streaming progress
func (s *Server) handleDeploySSE(w http.ResponseWriter, r *http.Request, req compose.DeployRequest) {
	startTime := time.Now()
	metrics.Global.IncrementActive()
	defer metrics.Global.DecrementActive()

	// Determine operation timeout
	timeout := time.Duration(req.Timeout) * time.Second
	if timeout <= 0 {
		timeout = 30 * time.Minute // Default
	}

	// Create context with timeout
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	defer cancel()

	// SSE headers
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no") // Disable nginx buffering

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "SSE not supported", http.StatusInternalServerError)
		return
	}

	s.log.WithFields(logrus.Fields{
		"deployment_id": req.DeploymentID,
		"project_name":  req.ProjectName,
		"action":        req.Action,
		"host_type":     compose.GetHostType(req),
	}).Info("Deployment started (SSE)")

	// Create Docker client
	dockerClient, err := s.createDockerClient(req)
	if err != nil {
		s.log.WithError(err).Error("Failed to create Docker client")
		errResp := compose.DeployResult{
			DeploymentID: req.DeploymentID,
			Success:      false,
			Error:        compose.NewDockerError(err.Error()),
		}
		data, _ := json.Marshal(errResp)
		fmt.Fprintf(w, "event: complete\ndata: %s\n\n", data)
		flusher.Flush()
		return
	}
	defer dockerClient.Close()

	// Keepalive ticker - send comment every 15s to prevent connection timeout
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	// Channel for deployment result
	resultCh := make(chan *compose.DeployResult, 1)

	// Progress channel for thread-safe writes
	progressCh := make(chan compose.ProgressEvent, 100)

	// Start deployment in goroutine
	go func() {
		// Create compose service with progress callback
		svc := compose.NewService(dockerClient, s.log, compose.WithProgressCallback(
			func(event compose.ProgressEvent) {
				select {
				case progressCh <- event:
				default:
					// Channel full, skip event (better than blocking)
				}
			},
		))

		result := svc.Deploy(ctx, req)
		close(progressCh)
		resultCh <- result
	}()

	// Event loop
	for {
		select {
		case event, ok := <-progressCh:
			if !ok {
				continue // Channel closed, wait for result
			}
			data, _ := json.Marshal(event)
			fmt.Fprintf(w, "event: progress\ndata: %s\n\n", data)
			flusher.Flush()

		case result := <-resultCh:
			// Record metrics
			duration := time.Since(startTime)
			metrics.Global.RecordDeployment(result.Success, result.PartialSuccess, duration)

			s.log.WithFields(logrus.Fields{
				"deployment_id":   req.DeploymentID,
				"success":         result.Success,
				"partial_success": result.PartialSuccess,
				"duration_secs":   duration.Seconds(),
				"service_count":   len(result.Services),
				"failed_count":    len(result.FailedServices),
			}).Info("Deployment completed (SSE)")

			data, _ := json.Marshal(result)
			fmt.Fprintf(w, "event: complete\ndata: %s\n\n", data)
			flusher.Flush()
			return

		case <-ticker.C:
			// SSE keepalive (comment line - ignored by SSE parsers)
			fmt.Fprintf(w, ": keepalive %d\n\n", time.Now().Unix())
			flusher.Flush()

		case <-ctx.Done():
			// Timeout or client disconnect
			errResp := compose.DeployResult{
				DeploymentID: req.DeploymentID,
				Success:      false,
				Error:        compose.NewInternalError("operation timeout"),
			}
			data, _ := json.Marshal(errResp)
			fmt.Fprintf(w, "event: complete\ndata: %s\n\n", data)
			flusher.Flush()
			return
		}
	}
}

// createDockerClient creates a Docker client based on the request
func (s *Server) createDockerClient(req compose.DeployRequest) (*client.Client, error) {
	if req.DockerHost == "" {
		// Local Docker socket
		return sharedDocker.CreateLocalClient()
	}

	// Remote Docker with TLS
	return sharedDocker.CreateRemoteClient(
		req.DockerHost,
		req.TLSCACert,
		req.TLSCert,
		req.TLSKey,
	)
}

// createDockerClientForUpdate creates a Docker client for the update endpoint
func (s *Server) createDockerClientForUpdate(dockerHost, caCert, cert, key string) (*client.Client, error) {
	if dockerHost == "" {
		// Local Docker socket
		return sharedDocker.CreateLocalClient()
	}

	// Remote Docker with TLS
	return sharedDocker.CreateRemoteClient(
		dockerHost,
		caCert,
		cert,
		key,
	)
}

// UpdateHTTPRequest is the HTTP request body for /update endpoint
type UpdateHTTPRequest struct {
	ContainerID   string               `json:"container_id"`
	NewImage      string               `json:"new_image"`
	StopTimeout   int                  `json:"stop_timeout,omitempty"`
	HealthTimeout int                  `json:"health_timeout,omitempty"`
	RegistryAuth  *update.RegistryAuth `json:"registry_auth,omitempty"`
	// For remote hosts (mTLS)
	DockerHost string `json:"docker_host,omitempty"`
	TLSCACert  string `json:"tls_ca_cert,omitempty"`
	TLSCert    string `json:"tls_cert,omitempty"`
	TLSKey     string `json:"tls_key,omitempty"`
	// Timeout for the entire operation
	Timeout int `json:"timeout,omitempty"`
}

// handleUpdate handles the /update endpoint with SSE streaming
func (s *Server) handleUpdate(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Parse request
	var req UpdateHTTPRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, fmt.Sprintf("Invalid request: %v", err), http.StatusBadRequest)
		return
	}

	// Validate required fields
	if req.ContainerID == "" || req.NewImage == "" {
		http.Error(w, "Missing required fields: container_id, new_image", http.StatusBadRequest)
		return
	}

	// Check if client wants SSE
	acceptHeader := r.Header.Get("Accept")
	useSSE := acceptHeader == "text/event-stream"

	if useSSE {
		s.handleUpdateSSE(w, r, req)
	} else {
		s.handleUpdateJSON(w, r, req)
	}
}

// handleUpdateJSON handles update with JSON response (no streaming)
func (s *Server) handleUpdateJSON(w http.ResponseWriter, r *http.Request, req UpdateHTTPRequest) {
	startTime := time.Now()
	metrics.Global.IncrementActive()
	defer metrics.Global.DecrementActive()

	s.log.WithFields(logrus.Fields{
		"container_id": req.ContainerID,
		"new_image":    req.NewImage,
	}).Info("Update started")

	// Create Docker client
	dockerClient, err := s.createDockerClientForUpdate(
		req.DockerHost, req.TLSCACert, req.TLSCert, req.TLSKey,
	)
	if err != nil {
		s.log.WithError(err).Error("Failed to create Docker client")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		json.NewEncoder(w).Encode(update.UpdateResult{
			Success:        false,
			OldContainerID: req.ContainerID,
			Error:          fmt.Sprintf("Failed to create Docker client: %v", err),
		})
		return
	}
	defer dockerClient.Close()

	// Detect runtime options (Podman, API version)
	options := update.DetectOptions(r.Context(), dockerClient, s.log)

	// Create updater
	updater := update.NewUpdater(dockerClient, s.log, options)

	// Execute update
	updateReq := update.UpdateRequest{
		ContainerID:   req.ContainerID,
		NewImage:      req.NewImage,
		StopTimeout:   req.StopTimeout,
		HealthTimeout: req.HealthTimeout,
		RegistryAuth:  req.RegistryAuth,
	}
	result := updater.Update(r.Context(), updateReq)

	// Record metrics
	duration := time.Since(startTime)
	metrics.Global.RecordDeployment(result.Success, false, duration)

	s.log.WithFields(logrus.Fields{
		"container_id":   req.ContainerID,
		"success":        result.Success,
		"new_container":  result.NewContainerID,
		"duration_secs":  duration.Seconds(),
	}).Info("Update completed")

	// Return result
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(result)
}

// handleUpdateSSE handles update with SSE streaming progress
func (s *Server) handleUpdateSSE(w http.ResponseWriter, r *http.Request, req UpdateHTTPRequest) {
	startTime := time.Now()
	metrics.Global.IncrementActive()
	defer metrics.Global.DecrementActive()

	// Determine operation timeout
	timeout := time.Duration(req.Timeout) * time.Second
	if timeout <= 0 {
		timeout = 30 * time.Minute // Default
	}

	// Create context with timeout
	ctx, cancel := context.WithTimeout(r.Context(), timeout)
	defer cancel()

	// SSE headers
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no") // Disable nginx buffering

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "SSE not supported", http.StatusInternalServerError)
		return
	}

	s.log.WithFields(logrus.Fields{
		"container_id": req.ContainerID,
		"new_image":    req.NewImage,
	}).Info("Update started (SSE)")

	// Create Docker client
	dockerClient, err := s.createDockerClientForUpdate(
		req.DockerHost, req.TLSCACert, req.TLSCert, req.TLSKey,
	)
	if err != nil {
		s.log.WithError(err).Error("Failed to create Docker client")
		errResp := update.UpdateResult{
			Success:        false,
			OldContainerID: req.ContainerID,
			Error:          fmt.Sprintf("Failed to create Docker client: %v", err),
		}
		data, _ := json.Marshal(errResp)
		fmt.Fprintf(w, "event: complete\ndata: %s\n\n", data)
		flusher.Flush()
		return
	}
	defer dockerClient.Close()

	// Keepalive ticker - send comment every 15s to prevent connection timeout
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	// Channel for update result
	resultCh := make(chan *update.UpdateResult, 1)

	// Progress channels for thread-safe writes
	progressCh := make(chan update.ProgressEvent, 100)
	pullProgressCh := make(chan update.PullProgressEvent, 100)

	// Start update in goroutine
	go func() {
		// Detect runtime options (Podman, API version)
		options := update.DetectOptions(ctx, dockerClient, s.log)

		// Add progress callbacks
		options.OnProgress = func(event update.ProgressEvent) {
			select {
			case progressCh <- event:
			default:
				// Channel full, skip event
			}
		}
		options.OnPullProgress = func(event update.PullProgressEvent) {
			select {
			case pullProgressCh <- event:
			default:
				// Channel full, skip event
			}
		}

		// Create updater
		updater := update.NewUpdater(dockerClient, s.log, options)

		// Execute update
		updateReq := update.UpdateRequest{
			ContainerID:   req.ContainerID,
			NewImage:      req.NewImage,
			StopTimeout:   req.StopTimeout,
			HealthTimeout: req.HealthTimeout,
			RegistryAuth:  req.RegistryAuth,
		}
		result := updater.Update(ctx, updateReq)

		close(progressCh)
		close(pullProgressCh)
		resultCh <- result
	}()

	// Event loop
	for {
		select {
		case event, ok := <-progressCh:
			if !ok {
				continue // Channel closed, wait for result
			}
			data, _ := json.Marshal(event)
			fmt.Fprintf(w, "event: progress\ndata: %s\n\n", data)
			flusher.Flush()

		case event, ok := <-pullProgressCh:
			if !ok {
				continue // Channel closed, wait for result
			}
			data, _ := json.Marshal(event)
			fmt.Fprintf(w, "event: pull_progress\ndata: %s\n\n", data)
			flusher.Flush()

		case result := <-resultCh:
			// Record metrics
			duration := time.Since(startTime)
			metrics.Global.RecordDeployment(result.Success, false, duration)

			s.log.WithFields(logrus.Fields{
				"container_id":  req.ContainerID,
				"success":       result.Success,
				"new_container": result.NewContainerID,
				"duration_secs": duration.Seconds(),
			}).Info("Update completed (SSE)")

			data, _ := json.Marshal(result)
			fmt.Fprintf(w, "event: complete\ndata: %s\n\n", data)
			flusher.Flush()
			return

		case <-ticker.C:
			// SSE keepalive (comment line - ignored by SSE parsers)
			fmt.Fprintf(w, ": keepalive %d\n\n", time.Now().Unix())
			flusher.Flush()

		case <-ctx.Done():
			// Timeout or client disconnect
			errResp := update.UpdateResult{
				Success:        false,
				OldContainerID: req.ContainerID,
				Error:          "operation timeout",
			}
			data, _ := json.Marshal(errResp)
			fmt.Fprintf(w, "event: complete\ndata: %s\n\n", data)
			flusher.Flush()
			return
		}
	}
}
