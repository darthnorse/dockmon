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
		persistEnabled: true,
	}
)

// mainSettingsProvider holds the live retention / points_per_view config that
// the retention scheduler and the settings endpoint (Task 17) both share.
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
// Used by main() during startup and will be read by Task 17's hot-reload
// handler once cascade rebuilds on config change are wired up.
func (p *mainSettingsProvider) PointsPerView() int {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.pointsPerView
}

// PersistEnabled returns whether stats persistence is currently accepting
// writes. Task 17 will flip this at runtime; Tasks 18+ will consult it on
// the ingest path.
func (p *mainSettingsProvider) PersistEnabled() bool {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.persistEnabled
}

// Update atomically replaces the live config. Task 17's settings handler
// calls this when Python pushes new values.
func (p *mainSettingsProvider) Update(retentionDays, pointsPerView int, enabled bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.retentionDays = retentionDays
	p.pointsPerView = pointsPerView
	p.persistEnabled = enabled
}
