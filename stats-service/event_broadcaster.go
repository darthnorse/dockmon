package main

import (
	"encoding/json"
	"log"
	"sync"

	"github.com/gorilla/websocket"
)

// EventBroadcaster manages WebSocket connections and broadcasts events
type EventBroadcaster struct {
	mu             sync.RWMutex
	connections    map[*websocket.Conn]*sync.Mutex // Each connection has its own write mutex
	maxConnections int
}

// NewEventBroadcaster creates a new event broadcaster
func NewEventBroadcaster() *EventBroadcaster {
	return &EventBroadcaster{
		connections:    make(map[*websocket.Conn]*sync.Mutex),
		maxConnections: 100, // Limit to 100 concurrent WebSocket connections
	}
}

// AddConnection registers a new WebSocket connection
func (eb *EventBroadcaster) AddConnection(conn *websocket.Conn) error {
	eb.mu.Lock()
	defer eb.mu.Unlock()

	// Check connection limit
	if len(eb.connections) >= eb.maxConnections {
		log.Printf("WebSocket connection limit reached (%d), rejecting new connection", eb.maxConnections)
		return &websocket.CloseError{Code: websocket.ClosePolicyViolation, Text: "Connection limit reached"}
	}

	eb.connections[conn] = &sync.Mutex{} // Create a dedicated mutex for this connection
	log.Printf("WebSocket connected to events. Total connections: %d", len(eb.connections))
	return nil
}

// RemoveConnection unregisters a WebSocket connection
func (eb *EventBroadcaster) RemoveConnection(conn *websocket.Conn) {
	eb.mu.Lock()
	defer eb.mu.Unlock()
	delete(eb.connections, conn)
	log.Printf("WebSocket disconnected from events. Total connections: %d", len(eb.connections))
}

// Broadcast sends an event to all connected WebSocket clients
func (eb *EventBroadcaster) Broadcast(event DockerEvent) {
	// Marshal event to JSON
	data, err := json.Marshal(event)
	if err != nil {
		log.Printf("Error marshaling event: %v", err)
		return
	}

	// Track dead connections
	var deadConnections []*websocket.Conn

	// Get snapshot of connections with their mutexes
	eb.mu.RLock()
	connMutexes := make(map[*websocket.Conn]*sync.Mutex, len(eb.connections))
	for conn, mu := range eb.connections {
		connMutexes[conn] = mu
	}
	eb.mu.RUnlock()

	// Send to all connections (with per-connection write lock)
	for conn, mu := range connMutexes {
		mu.Lock()
		err := conn.WriteMessage(websocket.TextMessage, data)
		mu.Unlock()

		if err != nil {
			log.Printf("Error sending event to WebSocket: %v", err)
			deadConnections = append(deadConnections, conn)
		}
	}

	// Clean up dead connections
	if len(deadConnections) > 0 {
		// Remove from map first (fast, under lock)
		eb.mu.Lock()
		var connectionsToClose []*websocket.Conn
		for _, conn := range deadConnections {
			// Only delete if connection still exists in map
			if _, exists := eb.connections[conn]; exists {
				delete(eb.connections, conn)
				connectionsToClose = append(connectionsToClose, conn)
			}
		}
		eb.mu.Unlock()

		// Close connections outside lock (slow, can block)
		for _, conn := range connectionsToClose {
			conn.Close()
		}
	}
}

// GetConnectionCount returns the number of active WebSocket connections
func (eb *EventBroadcaster) GetConnectionCount() int {
	eb.mu.RLock()
	defer eb.mu.RUnlock()
	return len(eb.connections)
}

// CloseAll closes all WebSocket connections
func (eb *EventBroadcaster) CloseAll() {
	eb.mu.Lock()
	var connectionsToClose []*websocket.Conn
	for conn := range eb.connections {
		connectionsToClose = append(connectionsToClose, conn)
	}
	eb.connections = make(map[*websocket.Conn]*sync.Mutex)
	eb.mu.Unlock()

	// Close connections outside lock (can block on network I/O)
	for _, conn := range connectionsToClose {
		conn.Close()
	}

	log.Println("Closed all event WebSocket connections")
}
