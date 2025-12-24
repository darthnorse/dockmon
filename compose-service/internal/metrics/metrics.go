package metrics

import (
	"sync"
	"sync/atomic"
	"time"
)

// Metrics tracks deployment and update statistics
type Metrics struct {
	mu sync.RWMutex

	// Deployment metrics
	TotalDeployments  int64
	SuccessfulDeploys int64
	FailedDeploys     int64
	PartialDeploys    int64
	ActiveDeployments int32

	// Update metrics (container updates via /update endpoint)
	TotalUpdates     int64
	SuccessfulUpdates int64
	FailedUpdates     int64
	ActiveUpdates     int32

	// Rolling average of last 100 deployments
	recentDurations []time.Duration
}

// Global is the singleton metrics instance
var Global = &Metrics{
	recentDurations: make([]time.Duration, 0, 100),
}

// IncrementActive increments active deployment counter
func (m *Metrics) IncrementActive() {
	atomic.AddInt32(&m.ActiveDeployments, 1)
}

// DecrementActive decrements active deployment counter
func (m *Metrics) DecrementActive() {
	atomic.AddInt32(&m.ActiveDeployments, -1)
}

// IncrementActiveUpdates increments active update counter
func (m *Metrics) IncrementActiveUpdates() {
	atomic.AddInt32(&m.ActiveUpdates, 1)
}

// DecrementActiveUpdates decrements active update counter
func (m *Metrics) DecrementActiveUpdates() {
	atomic.AddInt32(&m.ActiveUpdates, -1)
}

// RecordUpdate records a completed container update
func (m *Metrics) RecordUpdate(success bool) {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.TotalUpdates++
	if success {
		m.SuccessfulUpdates++
	} else {
		m.FailedUpdates++
	}
}

// RecordDeployment records a completed deployment
func (m *Metrics) RecordDeployment(success, partial bool, duration time.Duration) {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.TotalDeployments++
	if success {
		m.SuccessfulDeploys++
	} else if partial {
		m.PartialDeploys++
	} else {
		m.FailedDeploys++
	}

	// Rolling average of last 100 deployments
	m.recentDurations = append(m.recentDurations, duration)
	if len(m.recentDurations) > 100 {
		m.recentDurations = m.recentDurations[1:]
	}
}

// Snapshot returns current metrics as a map (for JSON encoding)
func (m *Metrics) Snapshot() map[string]interface{} {
	m.mu.RLock()
	defer m.mu.RUnlock()

	// Calculate average duration
	var avgDuration float64
	if len(m.recentDurations) > 0 {
		var total time.Duration
		for _, d := range m.recentDurations {
			total += d
		}
		avgDuration = total.Seconds() / float64(len(m.recentDurations))
	}

	return map[string]interface{}{
		"total_deployments":    m.TotalDeployments,
		"successful":           m.SuccessfulDeploys,
		"failed":               m.FailedDeploys,
		"partial":              m.PartialDeploys,
		"active":               atomic.LoadInt32(&m.ActiveDeployments),
		"avg_duration_seconds": avgDuration,
		// Update metrics
		"total_updates":      m.TotalUpdates,
		"successful_updates": m.SuccessfulUpdates,
		"failed_updates":     m.FailedUpdates,
		"active_updates":     atomic.LoadInt32(&m.ActiveUpdates),
	}
}

// Reset clears all metrics (for testing)
func (m *Metrics) Reset() {
	m.mu.Lock()
	defer m.mu.Unlock()

	m.TotalDeployments = 0
	m.SuccessfulDeploys = 0
	m.FailedDeploys = 0
	m.PartialDeploys = 0
	atomic.StoreInt32(&m.ActiveDeployments, 0)
	m.TotalUpdates = 0
	m.SuccessfulUpdates = 0
	m.FailedUpdates = 0
	atomic.StoreInt32(&m.ActiveUpdates, 0)
	m.recentDurations = m.recentDurations[:0]
}
