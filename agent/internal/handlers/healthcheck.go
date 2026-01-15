package handlers

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/sirupsen/logrus"
)

// HealthCheckConfig represents a container health check configuration
type HealthCheckConfig struct {
	ContainerID         string            `json:"container_id"`
	HostID              string            `json:"host_id"`
	Enabled             bool              `json:"enabled"`
	URL                 string            `json:"url"`
	Method              string            `json:"method"`
	ExpectedStatusCodes string            `json:"expected_status_codes"`
	TimeoutSeconds      int               `json:"timeout_seconds"`
	CheckIntervalSeconds int              `json:"check_interval_seconds"`
	FollowRedirects     bool              `json:"follow_redirects"`
	VerifySSL           bool              `json:"verify_ssl"`
	HeadersJSON         string            `json:"headers_json"`
	AuthConfigJSON      string            `json:"auth_config_json"`

	// Parsed fields (cached)
	parsedStatusCodes []int
	parsedHeaders     map[string]string
	parsedAuth        *AuthConfig
}

// AuthConfig represents authentication configuration
type AuthConfig struct {
	Type     string `json:"type"`     // "basic" or "bearer"
	Username string `json:"username"` // for basic auth
	Password string `json:"password"` // for basic auth
	Token    string `json:"token"`    // for bearer auth
}

// HealthCheckResult represents the result of a health check
type HealthCheckResult struct {
	ContainerID    string `json:"container_id"`
	HostID         string `json:"host_id"`
	Healthy        bool   `json:"healthy"`
	StatusCode     int    `json:"status_code,omitempty"`
	ResponseTimeMs int64  `json:"response_time_ms"`
	ErrorMessage   string `json:"error_message,omitempty"`
	Timestamp      string `json:"timestamp"`
}

// HealthCheckHandler manages container health checks
type HealthCheckHandler struct {
	configs   map[string]*HealthCheckConfig // key: container_id
	mu        sync.RWMutex
	log       *logrus.Logger
	sendEvent func(msgType string, payload interface{}) error
	stopChan  chan struct{}
	stopOnce  sync.Once // Ensures stopChan is only closed once
	wg        sync.WaitGroup
}

// NewHealthCheckHandler creates a new health check handler
func NewHealthCheckHandler(log *logrus.Logger, sendEvent func(string, interface{}) error) *HealthCheckHandler {
	return &HealthCheckHandler{
		configs:   make(map[string]*HealthCheckConfig),
		log:       log,
		sendEvent: sendEvent,
		stopChan:  make(chan struct{}),
	}
}

// Start starts the health check loop
func (h *HealthCheckHandler) Start(ctx context.Context) {
	h.wg.Add(1)
	go h.healthCheckLoop(ctx)
	h.log.Info("Health check handler started")
}

// Stop stops the health check handler
func (h *HealthCheckHandler) Stop() {
	h.stopOnce.Do(func() {
		close(h.stopChan)
	})
	h.wg.Wait()
	h.log.Info("Health check handler stopped")
}

// UpdateConfig adds or updates a health check configuration
func (h *HealthCheckHandler) UpdateConfig(config *HealthCheckConfig) {
	h.mu.Lock()
	defer h.mu.Unlock()

	// Parse status codes
	config.parsedStatusCodes = h.parseStatusCodes(config.ExpectedStatusCodes)

	// Parse headers
	if config.HeadersJSON != "" {
		var headers map[string]string
		if err := json.Unmarshal([]byte(config.HeadersJSON), &headers); err == nil {
			config.parsedHeaders = headers
		} else {
			h.log.WithError(err).Warnf("Failed to parse headers_json for %s", config.ContainerID)
		}
	}

	// Parse auth config
	if config.AuthConfigJSON != "" {
		var auth AuthConfig
		if err := json.Unmarshal([]byte(config.AuthConfigJSON), &auth); err == nil {
			config.parsedAuth = &auth
		} else {
			h.log.WithError(err).Warnf("Failed to parse auth_config_json for %s", config.ContainerID)
		}
	}

	h.configs[config.ContainerID] = config
	h.log.WithFields(logrus.Fields{
		"container_id": config.ContainerID,
		"url":          config.URL,
		"enabled":      config.Enabled,
		"interval":     config.CheckIntervalSeconds,
	}).Info("Health check config updated")
}

// RemoveConfig removes a health check configuration
func (h *HealthCheckHandler) RemoveConfig(containerID string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.configs, containerID)
	h.log.WithField("container_id", containerID).Info("Health check config removed")
}

// SyncConfigs replaces all configs with the provided list
func (h *HealthCheckHandler) SyncConfigs(configs []HealthCheckConfig) {
	h.mu.Lock()
	defer h.mu.Unlock()

	// Clear existing configs
	h.configs = make(map[string]*HealthCheckConfig)

	// Add new configs
	for i := range configs {
		config := &configs[i]
		config.parsedStatusCodes = h.parseStatusCodes(config.ExpectedStatusCodes)

		if config.HeadersJSON != "" {
			var headers map[string]string
			if err := json.Unmarshal([]byte(config.HeadersJSON), &headers); err == nil {
				config.parsedHeaders = headers
			}
		}

		if config.AuthConfigJSON != "" {
			var auth AuthConfig
			if err := json.Unmarshal([]byte(config.AuthConfigJSON), &auth); err == nil {
				config.parsedAuth = &auth
			}
		}

		h.configs[config.ContainerID] = config
	}

	h.log.WithField("count", len(configs)).Info("Health check configs synced")
}

// parseStatusCodes parses a comma-separated list of status codes
// Supports ranges like "200-299" and individual codes like "200,201,204"
func (h *HealthCheckHandler) parseStatusCodes(codes string) []int {
	if codes == "" {
		return []int{200}
	}

	var result []int
	parts := strings.Split(codes, ",")

	for _, part := range parts {
		part = strings.TrimSpace(part)

		// Check for range (e.g., "200-299")
		if strings.Contains(part, "-") {
			rangeParts := strings.Split(part, "-")
			if len(rangeParts) == 2 {
				start, err1 := strconv.Atoi(strings.TrimSpace(rangeParts[0]))
				end, err2 := strconv.Atoi(strings.TrimSpace(rangeParts[1]))
				if err1 == nil && err2 == nil && start <= end {
					for i := start; i <= end; i++ {
						result = append(result, i)
					}
				}
			}
		} else {
			// Single code
			if code, err := strconv.Atoi(part); err == nil {
				result = append(result, code)
			}
		}
	}

	if len(result) == 0 {
		return []int{200}
	}
	return result
}

// healthCheckLoop runs periodic health checks
func (h *HealthCheckHandler) healthCheckLoop(ctx context.Context) {
	defer h.wg.Done()

	// Track last check time for each container
	lastCheck := make(map[string]time.Time)

	ticker := time.NewTicker(1 * time.Second) // Check every second, but respect individual intervals
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			h.log.Info("Health check loop: context cancelled")
			return
		case <-h.stopChan:
			h.log.Info("Health check loop: stop signal received")
			return
		case <-ticker.C:
			h.runDueChecks(ctx, lastCheck)
		}
	}
}

// runDueChecks runs health checks that are due
func (h *HealthCheckHandler) runDueChecks(ctx context.Context, lastCheck map[string]time.Time) {
	h.mu.RLock()
	defer h.mu.RUnlock()

	now := time.Now()

	for containerID, config := range h.configs {
		if !config.Enabled {
			continue
		}

		// Check if this check is due
		last, exists := lastCheck[containerID]
		interval := time.Duration(config.CheckIntervalSeconds) * time.Second

		if !exists || now.Sub(last) >= interval {
			// Run check in goroutine to avoid blocking
			go h.performCheck(ctx, config)
			lastCheck[containerID] = now
		}
	}
}

// performCheck performs a single health check
func (h *HealthCheckHandler) performCheck(ctx context.Context, config *HealthCheckConfig) {
	startTime := time.Now()

	// Create HTTP client with appropriate settings
	transport := &http.Transport{
		TLSClientConfig: &tls.Config{
			InsecureSkipVerify: !config.VerifySSL,
		},
	}

	// Handle follow_redirects
	var checkRedirect func(req *http.Request, via []*http.Request) error
	if !config.FollowRedirects {
		checkRedirect = func(req *http.Request, via []*http.Request) error {
			return http.ErrUseLastResponse
		}
	}

	client := &http.Client{
		Transport:     transport,
		Timeout:       time.Duration(config.TimeoutSeconds) * time.Second,
		CheckRedirect: checkRedirect,
	}
	defer client.CloseIdleConnections()

	// Create request
	method := config.Method
	if method == "" {
		method = "GET"
	}

	req, err := http.NewRequestWithContext(ctx, method, config.URL, nil)
	if err != nil {
		h.sendResult(config, false, 0, time.Since(startTime).Milliseconds(), fmt.Sprintf("Failed to create request: %v", err))
		return
	}

	// Add headers
	if config.parsedHeaders != nil {
		for key, value := range config.parsedHeaders {
			req.Header.Set(key, value)
		}
	}

	// Add auth
	if config.parsedAuth != nil {
		switch config.parsedAuth.Type {
		case "basic":
			req.SetBasicAuth(config.parsedAuth.Username, config.parsedAuth.Password)
		case "bearer":
			req.Header.Set("Authorization", "Bearer "+config.parsedAuth.Token)
		}
	}

	// Perform request
	resp, err := client.Do(req)
	responseTimeMs := time.Since(startTime).Milliseconds()

	if err != nil {
		var errorMsg string
		if ctx.Err() != nil {
			errorMsg = "Request cancelled"
		} else if strings.Contains(err.Error(), "timeout") || strings.Contains(err.Error(), "deadline exceeded") {
			errorMsg = fmt.Sprintf("Timeout after %ds", config.TimeoutSeconds)
		} else if strings.Contains(err.Error(), "connection refused") {
			errorMsg = "Connection refused"
		} else if strings.Contains(err.Error(), "no such host") {
			errorMsg = "Host not found"
		} else {
			errorMsg = fmt.Sprintf("Connection failed: %.100s", err.Error())
		}
		h.sendResult(config, false, 0, responseTimeMs, errorMsg)
		return
	}
	defer resp.Body.Close()

	// Check status code
	isHealthy := false
	for _, code := range config.parsedStatusCodes {
		if resp.StatusCode == code {
			isHealthy = true
			break
		}
	}

	var errorMsg string
	if !isHealthy {
		errorMsg = fmt.Sprintf("Status %d", resp.StatusCode)
	}

	h.sendResult(config, isHealthy, resp.StatusCode, responseTimeMs, errorMsg)
}

// sendResult sends the health check result to the backend
func (h *HealthCheckHandler) sendResult(config *HealthCheckConfig, healthy bool, statusCode int, responseTimeMs int64, errorMsg string) {
	result := HealthCheckResult{
		ContainerID:    config.ContainerID,
		HostID:         config.HostID,
		Healthy:        healthy,
		StatusCode:     statusCode,
		ResponseTimeMs: responseTimeMs,
		ErrorMessage:   errorMsg,
		Timestamp:      time.Now().UTC().Format(time.RFC3339),
	}

	if err := h.sendEvent("health_check_result", result); err != nil {
		h.log.WithError(err).WithField("container_id", config.ContainerID).Warn("Failed to send health check result")
	} else if healthy {
		h.log.WithFields(logrus.Fields{
			"container_id":     config.ContainerID,
			"status_code":      statusCode,
			"response_time_ms": responseTimeMs,
		}).Debug("Health check passed")
	} else {
		h.log.WithFields(logrus.Fields{
			"container_id":     config.ContainerID,
			"status_code":      statusCode,
			"response_time_ms": responseTimeMs,
			"error":            errorMsg,
		}).Warn("Health check failed")
	}
}
