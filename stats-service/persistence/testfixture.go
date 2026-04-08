package persistence

import (
	"database/sql"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
)

// MakeFixtureDBForTest creates a sqlite file with the schema this package
// expects and returns its path. Exported so handler tests in the parent
// stats-service package can use it from their own _test.go files.
//
// The function is in a normal .go file (not _test.go) so it's compiled into
// production binaries, but it takes *testing.T so production code can't
// call it — *testing.T is only constructible from test code.
func MakeFixtureDBForTest(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "test.db")
	conn, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer conn.Close()

	stmts := []string{
		`CREATE TABLE docker_hosts (id TEXT PRIMARY KEY, name TEXT)`,
		`CREATE TABLE agents (id TEXT PRIMARY KEY, host_id TEXT NOT NULL)`,
		`CREATE TABLE global_settings (
			id INTEGER PRIMARY KEY,
			stats_persistence_enabled BOOLEAN NOT NULL DEFAULT 1,
			stats_retention_days INTEGER NOT NULL DEFAULT 30,
			stats_points_per_view INTEGER NOT NULL DEFAULT 500
		)`,
		`INSERT INTO global_settings (id) VALUES (1)`,
		`CREATE TABLE container_stats_history (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			container_id TEXT NOT NULL,
			host_id TEXT NOT NULL REFERENCES docker_hosts(id) ON DELETE CASCADE,
			timestamp INTEGER NOT NULL,
			resolution TEXT NOT NULL,
			cpu_percent REAL,
			memory_usage INTEGER,
			memory_limit INTEGER,
			network_bps REAL,
			UNIQUE (container_id, resolution, timestamp)
		)`,
		`CREATE INDEX idx_container_stats_host ON container_stats_history (host_id)`,
		`CREATE TABLE host_stats_history (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			host_id TEXT NOT NULL REFERENCES docker_hosts(id) ON DELETE CASCADE,
			timestamp INTEGER NOT NULL,
			resolution TEXT NOT NULL,
			cpu_percent REAL,
			memory_percent REAL,
			memory_used_bytes INTEGER,
			memory_limit_bytes INTEGER,
			network_bps REAL,
			container_count INTEGER,
			UNIQUE (host_id, resolution, timestamp)
		)`,
	}
	for _, s := range stmts {
		if _, err := conn.Exec(s); err != nil {
			t.Fatalf("seed: %v", err)
		}
	}
	return path
}
