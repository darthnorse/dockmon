package handlers

import (
	"reflect"
	"sync"

	"github.com/darthnorse/dockmon-agent/internal/client/statsmsg"
)

// StatsServiceSender is the narrow interface the stats handlers use to ship
// samples to stats-service. *client.StatsServiceClient satisfies this
// interface structurally — handlers cannot import `client` directly because
// `client` already imports `handlers` for the main WebSocket client.
type StatsServiceSender interface {
	Send(msg statsmsg.AgentStatsMsg)
}

// statsSink holds the optional stats-service dual-send target. Embedded by
// both the container and host stats handlers so the typed-nil normalization
// below exists exactly once.
type statsSink struct {
	// Protected by statsServiceMu because collection goroutines read it
	// concurrently with SetStatsServiceClient writes.
	statsService   StatsServiceSender
	statsServiceMu sync.RWMutex
}

// SetStatsServiceClient enables dual-send to stats-service. Pass nil to disable.
// Accepts any implementation of StatsServiceSender; *client.StatsServiceClient
// satisfies the interface structurally. Safe to call concurrently with
// collection goroutines.
func (s *statsSink) SetStatsServiceClient(c StatsServiceSender) {
	s.statsServiceMu.Lock()
	defer s.statsServiceMu.Unlock()
	// Normalize typed-nil to untyped nil so senders can use a simple nil
	// check. A typed-nil *client.StatsServiceClient would pass `!= nil`
	// but panic on the nil receiver.
	if c == nil || isNilPointer(c) {
		s.statsService = nil
		return
	}
	s.statsService = c
}

// sender returns the current dual-send target, or nil when disabled.
func (s *statsSink) sender() StatsServiceSender {
	s.statsServiceMu.RLock()
	defer s.statsServiceMu.RUnlock()
	return s.statsService
}

// isNilPointer reports whether v is an interface value wrapping a nil
// pointer (the "typed nil" footgun). It returns false for non-pointer
// concrete types, for non-nil pointers, and for an already-nil interface
// (callers should check `c == nil` separately for clarity).
func isNilPointer(v interface{}) bool {
	rv := reflect.ValueOf(v)
	return rv.Kind() == reflect.Ptr && rv.IsNil()
}
