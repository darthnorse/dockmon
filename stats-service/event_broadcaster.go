package main

import (
	"encoding/json"
	"log"
	"sync"

	"github.com/gorilla/websocket"
)

// EventBroadcaster manages WebSocket connections and broadcasts events
type EventBroadcaster struct {
	mu          sync.RWMutex
	connections map[*websocket.Conn]bool
}

// NewEventBroadcaster creates a new event broadcaster
func NewEventBroadcaster() *EventBroadcaster {
	return &EventBroadcaster{
		connections: make(map[*websocket.Conn]bool),
	}
}

// AddConnection registers a new WebSocket connection
func (eb *EventBroadcaster) AddConnection(conn *websocket.Conn) {
	eb.mu.Lock()
	defer eb.mu.Unlock()
	eb.connections[conn] = true
	log.Printf("WebSocket connected to events. Total connections: %d", len(eb.connections))
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

	// Send to all connections
	eb.mu.RLock()
	for conn := range eb.connections {
		err := conn.WriteMessage(websocket.TextMessage, data)
		if err != nil {
			log.Printf("Error sending event to WebSocket: %v", err)
			deadConnections = append(deadConnections, conn)
		}
	}
	eb.mu.RUnlock()

	// Clean up dead connections (after releasing read lock)
	if len(deadConnections) > 0 {
		eb.mu.Lock()
		for _, conn := range deadConnections {
			// Only delete and close if connection still exists in map
			if _, exists := eb.connections[conn]; exists {
				delete(eb.connections, conn)
				conn.Close()
			}
		}
		eb.mu.Unlock()
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
	defer eb.mu.Unlock()

	for conn := range eb.connections {
		conn.Close()
	}

	eb.connections = make(map[*websocket.Conn]bool)
	log.Println("Closed all event WebSocket connections")
}
