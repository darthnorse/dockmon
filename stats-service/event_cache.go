package main

import (
	"sync"
)

// EventCache stores recent events for each host (ring buffer)
type EventCache struct {
	mu       sync.RWMutex
	events   map[string][]DockerEvent // key: hostID, value: ring buffer of events
	maxSize  int                      // maximum events to keep per host
}

// NewEventCache creates a new event cache
func NewEventCache(maxSize int) *EventCache {
	return &EventCache{
		events:  make(map[string][]DockerEvent),
		maxSize: maxSize,
	}
}

// AddEvent adds an event to the cache for a specific host
func (ec *EventCache) AddEvent(hostID string, event DockerEvent) {
	ec.mu.Lock()
	defer ec.mu.Unlock()

	// Initialize slice if needed
	if _, exists := ec.events[hostID]; !exists {
		ec.events[hostID] = make([]DockerEvent, 0, ec.maxSize)
	}

	// Add event
	ec.events[hostID] = append(ec.events[hostID], event)

	// Trim if over max size (keep most recent)
	if len(ec.events[hostID]) > ec.maxSize {
		ec.events[hostID] = ec.events[hostID][len(ec.events[hostID])-ec.maxSize:]
	}
}

// GetRecentEvents returns recent events for a specific host
func (ec *EventCache) GetRecentEvents(hostID string, limit int) []DockerEvent {
	ec.mu.RLock()
	defer ec.mu.RUnlock()

	events, exists := ec.events[hostID]
	if !exists || len(events) == 0 {
		return []DockerEvent{}
	}

	// Return last N events
	if limit <= 0 || limit > len(events) {
		limit = len(events)
	}

	// Return copy to avoid race conditions
	result := make([]DockerEvent, limit)
	copy(result, events[len(events)-limit:])
	return result
}

// GetAllRecentEvents returns recent events for all hosts
func (ec *EventCache) GetAllRecentEvents(limit int) map[string][]DockerEvent {
	ec.mu.RLock()
	defer ec.mu.RUnlock()

	result := make(map[string][]DockerEvent)

	for hostID, events := range ec.events {
		if len(events) == 0 {
			continue
		}

		// Get last N events
		count := limit
		if count <= 0 || count > len(events) {
			count = len(events)
		}

		// Copy to avoid race conditions
		hostEvents := make([]DockerEvent, count)
		copy(hostEvents, events[len(events)-count:])
		result[hostID] = hostEvents
	}

	return result
}

// ClearHost removes all cached events for a specific host
func (ec *EventCache) ClearHost(hostID string) {
	ec.mu.Lock()
	defer ec.mu.Unlock()
	delete(ec.events, hostID)
}

// GetStats returns cache statistics
func (ec *EventCache) GetStats() (hostCount int, totalEvents int) {
	ec.mu.RLock()
	defer ec.mu.RUnlock()

	hostCount = len(ec.events)
	for _, events := range ec.events {
		totalEvents += len(events)
	}
	return
}
