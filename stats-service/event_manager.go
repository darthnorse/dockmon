package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"log"
	"net"
	"net/http"
	"sync"
	"time"

	"github.com/docker/docker/api/types/events"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/client"
)

// DockerEvent represents a Docker container event
type DockerEvent struct {
	Action        string            `json:"action"`
	ContainerID   string            `json:"container_id"`
	ContainerName string            `json:"container_name"`
	Image         string            `json:"image"`
	HostID        string            `json:"host_id"`
	Timestamp     string            `json:"timestamp"`
	Attributes    map[string]string `json:"attributes"`
}

// EventManager manages Docker event streams for multiple hosts
type EventManager struct {
	mu           sync.RWMutex
	hosts        map[string]*eventStream // key: hostID
	broadcaster  *EventBroadcaster
	eventCache   *EventCache
}

// eventStream represents a single Docker host event stream
type eventStream struct {
	hostID    string
	hostAddr  string
	client    *client.Client
	ctx       context.Context
	cancel    context.CancelFunc
	active    bool
}

// createEventTLSOption creates a Docker client TLS option from PEM-encoded certificates
func createEventTLSOption(caCertPEM, certPEM, keyPEM string) (client.Opt, error) {
	// Parse CA certificate
	caCertPool := x509.NewCertPool()
	if !caCertPool.AppendCertsFromPEM([]byte(caCertPEM)) {
		return nil, fmt.Errorf("failed to parse CA certificate")
	}

	// Parse client certificate and key
	clientCert, err := tls.X509KeyPair([]byte(certPEM), []byte(keyPEM))
	if err != nil {
		return nil, fmt.Errorf("failed to parse client certificate/key: %v", err)
	}

	// Create TLS config
	tlsConfig := &tls.Config{
		Certificates: []tls.Certificate{clientCert},
		RootCAs:      caCertPool,
		MinVersion:   tls.VersionTLS12,
	}

	// Create HTTP client with TLS transport and timeouts
	// Note: No overall Timeout set because Docker API streaming operations (stats, events)
	// are long-running connections that should not be killed by a timeout
	httpClient := &http.Client{
		Transport: &http.Transport{
			DialContext: (&net.Dialer{
				Timeout:   30 * time.Second, // Connection establishment timeout
				KeepAlive: 30 * time.Second, // TCP keepalive interval
			}).DialContext,
			TLSClientConfig:       tlsConfig,
			TLSHandshakeTimeout:   10 * time.Second,
			IdleConnTimeout:       90 * time.Second,
			ResponseHeaderTimeout: 10 * time.Second,
		},
	}

	return client.WithHTTPClient(httpClient), nil
}

// NewEventManager creates a new event manager
func NewEventManager(broadcaster *EventBroadcaster, cache *EventCache) *EventManager {
	return &EventManager{
		hosts:       make(map[string]*eventStream),
		broadcaster: broadcaster,
		eventCache:  cache,
	}
}

// AddHost starts monitoring Docker events for a host
func (em *EventManager) AddHost(hostID, hostAddress, tlsCACert, tlsCert, tlsKey string) error {
	// Create Docker client FIRST (before acquiring lock or stopping old stream)
	var dockerClient *client.Client
	var err error

	if hostAddress == "" || hostAddress == "unix:///var/run/docker.sock" {
		// Local Docker socket
		dockerClient, err = client.NewClientWithOpts(
			client.FromEnv,
			client.WithAPIVersionNegotiation(),
		)
	} else {
		// Remote Docker host - check if TLS is needed
		clientOpts := []client.Opt{
			client.WithHost(hostAddress),
			client.WithAPIVersionNegotiation(),
		}

		// If TLS certificates provided, configure TLS
		if tlsCACert != "" && tlsCert != "" && tlsKey != "" {
			tlsOpt, err := createEventTLSOption(tlsCACert, tlsCert, tlsKey)
			if err != nil {
				return fmt.Errorf("failed to create TLS config: %v", err)
			}
			clientOpts = append(clientOpts, tlsOpt)
		}

		dockerClient, err = client.NewClientWithOpts(clientOpts...)
	}

	if err != nil {
		return err
	}

	// Now that new client is successfully created, acquire lock and swap
	em.mu.Lock()
	defer em.mu.Unlock()

	// If already monitoring, stop the old stream (only after new client succeeds)
	if stream, exists := em.hosts[hostID]; exists && stream.active {
		log.Printf("Stopping existing event monitoring for host %s to update", truncateID(hostID, 8))
		stream.cancel()
		stream.active = false
		if stream.client != nil {
			stream.client.Close()
		}
	}

	// Create context for this stream
	ctx, cancel := context.WithCancel(context.Background())

	stream := &eventStream{
		hostID:   hostID,
		hostAddr: hostAddress,
		client:   dockerClient,
		ctx:      ctx,
		cancel:   cancel,
		active:   true,
	}

	em.hosts[hostID] = stream

	// Start event stream in goroutine
	go em.streamEvents(stream)

	log.Printf("Started event monitoring for host %s (%s)", truncateID(hostID, 8), hostAddress)
	return nil
}

// RemoveHost stops monitoring events for a host
func (em *EventManager) RemoveHost(hostID string) {
	em.mu.Lock()
	defer em.mu.Unlock()

	if stream, exists := em.hosts[hostID]; exists {
		stream.cancel()
		stream.active = false
		if stream.client != nil {
			stream.client.Close()
		}

		// Clear cached events for this host
		em.eventCache.ClearHost(hostID)
		delete(em.hosts, hostID)
		log.Printf("Stopped event monitoring for host %s", truncateID(hostID, 8))
	}
}

// StopAll stops all event monitoring
func (em *EventManager) StopAll() {
	em.mu.Lock()
	defer em.mu.Unlock()

	for hostID, stream := range em.hosts {
		stream.cancel()
		stream.active = false
		if stream.client != nil {
			stream.client.Close()
		}
		log.Printf("Stopped event monitoring for host %s", truncateID(hostID, 8))
	}

	em.hosts = make(map[string]*eventStream)
}

// GetActiveHosts returns count of active event streams
func (em *EventManager) GetActiveHosts() int {
	em.mu.RLock()
	defer em.mu.RUnlock()
	return len(em.hosts)
}

// streamEvents listens to Docker events for a specific host
func (em *EventManager) streamEvents(stream *eventStream) {
	defer func() {
		if r := recover(); r != nil {
			log.Printf("Recovered from panic in event stream for %s: %v", truncateID(stream.hostID, 8), r)
		}
	}()

	// Retry loop with exponential backoff
	backoff := time.Second
	maxBackoff := 30 * time.Second

	for {
		select {
		case <-stream.ctx.Done():
			log.Printf("Event stream for host %s stopped", truncateID(stream.hostID, 8))
			return
		default:
		}

		// Listen to container events only
		eventFilters := filters.NewArgs()
		eventFilters.Add("type", "container")

		eventOptions := events.ListOptions{
			Filters: eventFilters,
		}

		eventsChan, errChan := stream.client.Events(stream.ctx, eventOptions)

		// Reset backoff on successful connection
		backoff = time.Second

		for {
			select {
			case <-stream.ctx.Done():
				return

			case err := <-errChan:
				if err != nil {
					log.Printf("Event stream error for host %s: %v (retrying in %v)", truncateID(stream.hostID, 8), err, backoff)
					time.Sleep(backoff)
					backoff = min(backoff*2, maxBackoff)
					goto reconnect
				}

			case event := <-eventsChan:
				// Process the event with panic recovery
				func() {
					defer func() {
						if r := recover(); r != nil {
							log.Printf("Recovered from panic in processEvent for host %s: %v", truncateID(stream.hostID, 8), r)
						}
					}()
					em.processEvent(stream.hostID, event)
				}()
			}
		}

	reconnect:
		// Brief pause before reconnecting
		time.Sleep(time.Second)
	}
}

// processEvent converts Docker event to our format and broadcasts it
func (em *EventManager) processEvent(hostID string, event events.Message) {
	// Extract container info
	containerID := event.Actor.ID

	// Safely extract attributes with defensive access pattern
	containerName := ""
	image := ""
	if attrs := event.Actor.Attributes; attrs != nil {
		if name, ok := attrs["name"]; ok {
			containerName = name
		}
		if img, ok := attrs["image"]; ok {
			image = img
		}
	}

	// Create our event
	dockerEvent := DockerEvent{
		Action:        string(event.Action),
		ContainerID:   containerID,
		ContainerName: containerName,
		Image:         image,
		HostID:        hostID,
		Timestamp:     time.Unix(event.Time, 0).Format(time.RFC3339),
		Attributes:    event.Actor.Attributes,
	}

	// Only log important events (not noisy exec_* events)
	action := dockerEvent.Action
	if action != "" && !isExecEvent(action) && isImportantEvent(action) {
		log.Printf("Event: %s - container %s (%s) on host %s",
			dockerEvent.Action,
			dockerEvent.ContainerName,
			truncateID(dockerEvent.ContainerID, 12),
			truncateID(hostID, 8))
	}

	// Add to cache
	em.eventCache.AddEvent(hostID, dockerEvent)

	// Broadcast to all WebSocket clients
	em.broadcaster.Broadcast(dockerEvent)
}

// isExecEvent checks if the event is an exec_* event (noisy)
func isExecEvent(action string) bool {
	return len(action) > 5 && action[:5] == "exec_"
}

// isImportantEvent checks if the event should be logged
func isImportantEvent(action string) bool {
	importantEvents := map[string]bool{
		"create":        true,
		"start":         true,
		"stop":          true,
		"die":           true,
		"kill":          true,
		"destroy":       true,
		"pause":         true,
		"unpause":       true,
		"restart":       true,
		"oom":           true,
		"health_status": true,
	}
	return importantEvents[action]
}
