package main

import (
	"sync"

	"github.com/dockmon/stats-service/persistence"
)

// Persistence subsystem state. Initialized in main() if the DB opens
// successfully; nil otherwise (persistence disabled, live stats keep working).
var (
	persistDB        *persistence.DB
	cascade          *persistence.Cascade
	writer           *persistence.Writer
	retention        *persistence.Retention
	settingsProvider = &mainSettingsProvider{
		retentionDays:  30,
		pointsPerView:  500,
		persistEnabled: false,
	}
)

// mainSettingsProvider holds the live retention / points_per_view config
// shared by the retention scheduler and the settings hot-reload endpoint.
// Thread-safe via RWMutex, matching the SettingsProvider interface contract.
type mainSettingsProvider struct {
	mu             sync.RWMutex
	retentionDays  int
	pointsPerView  int
	persistEnabled bool
}

// RetentionDays satisfies the persistence.SettingsProvider interface.
func (p *mainSettingsProvider) RetentionDays() int {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.retentionDays
}

// PointsPerView returns the current points_per_view under a read lock.
func (p *mainSettingsProvider) PointsPerView() int {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.pointsPerView
}

// PersistEnabled returns whether stats persistence is currently accepting
// writes. The settings hot-reload handler flips this at runtime; the
// aggregator consults it before feeding samples into the cascade.
func (p *mainSettingsProvider) PersistEnabled() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.persistEnabled
}

// ApplyPartialUpdate atomically applies a partial update to the live config,
// enforcing the same ranges as the Python-side Pydantic validator (1..30 for
// retention_days, 100..2000 for points_per_view). Out-of-range values are
// silently ignored — the Python side already rejects them with 422 before
// the push ever reaches here, so this is defense-in-depth only. Nil pointers
// leave the corresponding field unchanged. Returns the post-update snapshot
// so callers can echo it back in the response body.
func (p *mainSettingsProvider) ApplyPartialUpdate(
	persistEnabled *bool,
	retentionDays *int,
	pointsPerView *int,
) (bool, int, int) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if persistEnabled != nil {
		p.persistEnabled = *persistEnabled
	}
	if retentionDays != nil && *retentionDays >= 1 && *retentionDays <= 30 {
		p.retentionDays = *retentionDays
	}
	if pointsPerView != nil && *pointsPerView >= 100 && *pointsPerView <= 2000 {
		p.pointsPerView = *pointsPerView
	}
	return p.persistEnabled, p.retentionDays, p.pointsPerView
}
