package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
)

// Configuration with environment variable support
var config = struct {
	TokenFilePath       string
	Port                string
	AggregationInterval time.Duration
	EventCacheSize      int
	CleanupInterval     time.Duration
	MaxRequestBodySize  int64
	AllowedOrigins      string
}{
	TokenFilePath:       getEnv("TOKEN_FILE_PATH", "/tmp/stats-service-token"),
	Port:                getEnv("STATS_SERVICE_PORT", "8081"),
	AggregationInterval: getEnvDuration("AGGREGATION_INTERVAL", "1s"),
	EventCacheSize:      getEnvInt("EVENT_CACHE_SIZE", 100),
	CleanupInterval:     getEnvDuration("CLEANUP_INTERVAL", "60s"),
	MaxRequestBodySize:  getEnvInt64("MAX_REQUEST_BODY_SIZE", 1048576), // 1MB default
	AllowedOrigins:      getEnv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080,http://localhost,http://127.0.0.1"),
}

// getEnv gets environment variable with fallback
func getEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

// getEnvInt gets integer environment variable with fallback
func getEnvInt(key string, fallback int) int {
	if value := os.Getenv(key); value != "" {
		if intVal, err := strconv.Atoi(value); err == nil {
			return intVal
		}
	}
	return fallback
}

// getEnvInt64 gets int64 environment variable with fallback
func getEnvInt64(key string, fallback int64) int64 {
	if value := os.Getenv(key); value != "" {
		if intVal, err := strconv.ParseInt(value, 10, 64); err == nil {
			return intVal
		}
	}
	return fallback
}

// getEnvDuration gets duration environment variable with fallback
func getEnvDuration(key string, fallback string) time.Duration {
	value := getEnv(key, fallback)
	if duration, err := time.ParseDuration(value); err == nil {
		return duration
	}
	// Fallback parsing
	if duration, err := time.ParseDuration(fallback); err == nil {
		return duration
	}
	return 1 * time.Second // Ultimate fallback
}

// generateToken creates a cryptographically secure random token
func generateToken() (string, error) {
	bytes := make([]byte, 32) // 256-bit token
	if _, err := rand.Read(bytes); err != nil {
		return "", err
	}
	return hex.EncodeToString(bytes), nil
}

// limitRequestBody limits the size of request bodies
func limitRequestBody(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, config.MaxRequestBodySize)
		next(w, r)
	}
}

// jsonResponse writes a JSON response and handles encoding errors
func jsonResponse(w http.ResponseWriter, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(data); err != nil {
		log.Printf("Error encoding JSON response: %v", err)
		// Can't send error status if response already partially sent
	}
}

// authMiddleware validates the Bearer token
func authMiddleware(token string, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Get Authorization header
		authHeader := r.Header.Get("Authorization")
		expectedAuth := "Bearer " + token

		if authHeader != expectedAuth {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			log.Printf("Unauthorized request from %s to %s", r.RemoteAddr, r.URL.Path)
			return
		}

		next(w, r)
	}
}

func main() {
	log.Println("Starting DockMon Stats Service...")

	// Generate random token
	token, err := generateToken()
	if err != nil {
		log.Fatalf("Failed to generate token: %v", err)
	}

	// Write token to file for Python backend
	if err := os.WriteFile(config.TokenFilePath, []byte(token), 0600); err != nil {
		log.Fatalf("Failed to write token file: %v", err)
	}
	log.Printf("Generated temporary auth token for stats service")
	log.Printf("Configuration: port=%s, aggregation=%v, cache_size=%d, cleanup=%v",
		config.Port, config.AggregationInterval, config.EventCacheSize, config.CleanupInterval)

	// Create stats cache
	cache := NewStatsCache()

	// Create stream manager
	streamManager := NewStreamManager(cache)

	// Create aggregator with configured interval
	aggregator := NewAggregator(cache, config.AggregationInterval)

	// Create event management components with configured cache size
	eventCache := NewEventCache(config.EventCacheSize)
	eventBroadcaster := NewEventBroadcaster()
	eventManager := NewEventManager(eventBroadcaster, eventCache)

	// Create context for graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Start aggregator
	go aggregator.Start(ctx)

	// Start cleanup routine (remove stale stats every 60 seconds)
	go func() {
		ticker := time.NewTicker(60 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				cache.CleanStaleStats(60 * time.Second)
			}
		}
	}()

	// Create HTTP server
	mux := http.NewServeMux()

	// Health check endpoint
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		_, totalEvents := eventCache.GetStats()
		jsonResponse(w, map[string]interface{}{
			"status":            "ok",
			"service":           "dockmon-stats",
			"stats_streams":     streamManager.GetStreamCount(),
			"event_hosts":       eventManager.GetActiveHosts(),
			"event_connections": eventBroadcaster.GetConnectionCount(),
			"cached_events":     totalEvents,
		})
	})

	// Get all host stats (main endpoint for Python backend) - PROTECTED
	mux.HandleFunc("/api/stats/hosts", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		hostStats := cache.GetAllHostStats()
		json.NewEncoder(w).Encode(hostStats)
	}))

	// Get stats for a specific host - PROTECTED
	mux.HandleFunc("/api/stats/host/", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		hostID := r.URL.Path[len("/api/stats/host/"):]
		if hostID == "" {
			http.Error(w, "host_id required", http.StatusBadRequest)
			return
		}

		stats, ok := cache.GetHostStats(hostID)
		if !ok {
			http.NotFound(w, r)
			return
		}

		jsonResponse(w,stats)
	}))

	// Get all container stats (for debugging) - PROTECTED
	mux.HandleFunc("/api/stats/containers", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		containerStats := cache.GetAllContainerStats()
		json.NewEncoder(w).Encode(containerStats)
	}))

	// Start stream for a container (called by Python backend) - PROTECTED
	mux.HandleFunc("/api/streams/start", authMiddleware(token, limitRequestBody(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			ContainerID   string `json:"container_id"`
			ContainerName string `json:"container_name"`
			HostID        string `json:"host_id"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		// Validate required fields
		if req.ContainerID == "" || req.HostID == "" {
			http.Error(w, "container_id and host_id are required", http.StatusBadRequest)
			return
		}

		if err := streamManager.StartStream(ctx, req.ContainerID, req.ContainerName, req.HostID); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "started"})
	})))

	// Stop stream for a container - PROTECTED
	mux.HandleFunc("/api/streams/stop", authMiddleware(token, limitRequestBody(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			ContainerID string `json:"container_id"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		// Validate required fields
		if req.ContainerID == "" {
			http.Error(w, "container_id is required", http.StatusBadRequest)
			return
		}

		streamManager.StopStream(req.ContainerID)

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "stopped"})
	})))

	// Add Docker host - PROTECTED
	mux.HandleFunc("/api/hosts/add", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			HostID      string `json:"host_id"`
			HostAddress string `json:"host_address"`
			TLSCACert   string `json:"tls_ca_cert,omitempty"`
			TLSCert     string `json:"tls_cert,omitempty"`
			TLSKey      string `json:"tls_key,omitempty"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		// Validate required fields
		if req.HostID == "" || req.HostAddress == "" {
			http.Error(w, "host_id and host_address are required", http.StatusBadRequest)
			return
		}

		if err := streamManager.AddDockerHost(req.HostID, req.HostAddress, req.TLSCACert, req.TLSCert, req.TLSKey); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "added"})
	}))

	// Remove Docker host - PROTECTED
	mux.HandleFunc("/api/hosts/remove", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			HostID string `json:"host_id"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		// Validate required fields
		if req.HostID == "" {
			http.Error(w, "host_id is required", http.StatusBadRequest)
			return
		}

		streamManager.RemoveDockerHost(req.HostID)

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "removed"})
	}))

	// Debug endpoint - PROTECTED
	mux.HandleFunc("/debug/stats", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		containerCount, hostCount := cache.GetStats()
		jsonResponse(w, map[string]interface{}{
			"streams":    streamManager.GetStreamCount(),
			"containers": containerCount,
			"hosts":      hostCount,
		})
	}))

	// === Event Monitoring Endpoints ===

	// Start monitoring events for a host - PROTECTED
	mux.HandleFunc("/api/events/hosts/add", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			HostID      string `json:"host_id"`
			HostAddress string `json:"host_address"`
			TLSCACert   string `json:"tls_ca_cert,omitempty"`
			TLSCert     string `json:"tls_cert,omitempty"`
			TLSKey      string `json:"tls_key,omitempty"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		// Validate required fields
		if req.HostID == "" || req.HostAddress == "" {
			http.Error(w, "host_id and host_address are required", http.StatusBadRequest)
			return
		}

		if err := eventManager.AddHost(req.HostID, req.HostAddress, req.TLSCACert, req.TLSCert, req.TLSKey); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "started"})
	}))

	// Stop monitoring events for a host - PROTECTED
	mux.HandleFunc("/api/events/hosts/remove", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			HostID string `json:"host_id"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		// Validate required fields
		if req.HostID == "" {
			http.Error(w, "host_id is required", http.StatusBadRequest)
			return
		}

		eventManager.RemoveHost(req.HostID)

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "stopped"})
	}))

	// Get recent events - PROTECTED
	mux.HandleFunc("/api/events/recent", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		hostID := r.URL.Query().Get("host_id")

		var events interface{}
		if hostID != "" {
			// Get events for specific host
			events = eventCache.GetRecentEvents(hostID, 50)
		} else {
			// Get events for all hosts
			events = eventCache.GetAllRecentEvents(50)
		}

		jsonResponse(w,events)
	}))

	// WebSocket endpoint for event streaming - PROTECTED
	mux.HandleFunc("/ws/events", func(w http.ResponseWriter, r *http.Request) {
		// Validate token from query parameter or header
		tokenParam := r.URL.Query().Get("token")
		authHeader := r.Header.Get("Authorization")

		validToken := false
		if tokenParam == token {
			validToken = true
		} else if authHeader == "Bearer "+token {
			validToken = true
		}

		if !validToken {
			http.Error(w, "Unauthorized", http.StatusUnauthorized)
			log.Printf("Unauthorized WebSocket connection attempt from %s", r.RemoteAddr)
			return
		}

		// Upgrade to WebSocket
		upgrader := websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool {
				origin := r.Header.Get("Origin")
				if origin == "" {
					return true // Allow same-origin requests
				}
				// Check against configured allowed origins
				allowedOrigins := strings.Split(config.AllowedOrigins, ",")
				for _, allowed := range allowedOrigins {
					if strings.TrimSpace(allowed) == origin {
						return true
					}
				}
				return false
			},
		}

		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Printf("WebSocket upgrade failed: %v", err)
			return
		}

		// Register connection
		if err := eventBroadcaster.AddConnection(conn); err != nil {
			log.Printf("Failed to register connection: %v", err)
			conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.ClosePolicyViolation, "Connection limit reached"))
			conn.Close()
			return
		}

		// Handle connection (read loop to detect disconnect)
		go func() {
			defer func() {
				eventBroadcaster.RemoveConnection(conn)
				conn.Close()
			}()

			for {
				// Read messages (just to detect disconnect, we don't expect any)
				_, _, err := conn.ReadMessage()
				if err != nil {
					break
				}
			}
		}()
	})

	// Create server with configured port
	srv := &http.Server{
		Addr:         ":" + config.Port,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Start server in goroutine
	go func() {
		log.Printf("Stats service listening on %s", srv.Addr)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Server error: %v", err)
		}
	}()

	// Wait for interrupt signal
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	<-sigChan

	log.Println("Shutting down stats service...")

	// Graceful shutdown
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	// Stop all stats streams
	streamManager.StopAllStreams()

	// Stop all event monitoring
	eventManager.StopAll()

	// Close all event WebSocket connections
	eventBroadcaster.CloseAll()

	// Stop HTTP server
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("Server shutdown error: %v", err)
	}

	// Cancel context to stop aggregator
	cancel()

	// Clean up token file
	if err := os.Remove(config.TokenFilePath); err != nil {
		log.Printf("Warning: Failed to remove token file: %v", err)
	} else {
		log.Println("Removed token file")
	}

	log.Println("Stats service stopped")
}
