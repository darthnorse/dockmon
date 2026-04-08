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

// Update atomically replaces the live config. Task 17's settings handler
// calls this when Python pushes new values.
func (p *mainSettingsProvider) Update(retentionDays, pointsPerView int, enabled bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.retentionDays = retentionDays
	p.pointsPerView = pointsPerView
	p.persistEnabled = enabled
}
