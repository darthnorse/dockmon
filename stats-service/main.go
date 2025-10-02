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
	"syscall"
	"time"
)

const tokenFilePath = "/tmp/stats-service-token"

// generateToken creates a cryptographically secure random token
func generateToken() (string, error) {
	bytes := make([]byte, 32) // 256-bit token
	if _, err := rand.Read(bytes); err != nil {
		return "", err
	}
	return hex.EncodeToString(bytes), nil
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
	if err := os.WriteFile(tokenFilePath, []byte(token), 0600); err != nil {
		log.Fatalf("Failed to write token file: %v", err)
	}
	log.Println("Generated temporary auth token")

	// Create stats cache
	cache := NewStatsCache()

	// Create stream manager
	streamManager := NewStreamManager(cache)

	// Create aggregator (runs every 1 second)
	aggregator := NewAggregator(cache, 1*time.Second)

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
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":      "ok",
			"service":     "dockmon-stats",
			"streams":     streamManager.GetStreamCount(),
			"containers":  0,
			"hosts":       0,
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

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(stats)
	}))

	// Get all container stats (for debugging) - PROTECTED
	mux.HandleFunc("/api/stats/containers", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		containerStats := cache.GetAllContainerStats()
		json.NewEncoder(w).Encode(containerStats)
	}))

	// Start stream for a container (called by Python backend) - PROTECTED
	mux.HandleFunc("/api/streams/start", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
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

		if err := streamManager.StartStream(ctx, req.ContainerID, req.ContainerName, req.HostID); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "started"})
	}))

	// Stop stream for a container - PROTECTED
	mux.HandleFunc("/api/streams/stop", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
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

		streamManager.StopStream(req.ContainerID)

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "stopped"})
	}))

	// Add Docker host - PROTECTED
	mux.HandleFunc("/api/hosts/add", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req struct {
			HostID      string `json:"host_id"`
			HostAddress string `json:"host_address"`
		}

		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}

		if err := streamManager.AddDockerHost(req.HostID, req.HostAddress); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "added"})
	}))

	// Debug endpoint - PROTECTED
	mux.HandleFunc("/debug/stats", authMiddleware(token, func(w http.ResponseWriter, r *http.Request) {
		containerCount, hostCount := cache.GetStats()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"streams":    streamManager.GetStreamCount(),
			"containers": containerCount,
			"hosts":      hostCount,
		})
	}))

	// Create server
	srv := &http.Server{
		Addr:         ":8081",
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

	// Stop all streams
	streamManager.StopAllStreams()

	// Stop HTTP server
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("Server shutdown error: %v", err)
	}

	// Cancel context to stop aggregator
	cancel()

	log.Println("Stats service stopped")
}
