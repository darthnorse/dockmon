package persistence

import (
	"context"
	"database/sql"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
)

// makeFixtureDB creates a sqlite file with the schema this package expects.
// In real use Alembic creates this; for tests we create it inline.
func makeFixtureDB(t *testing.T) string {
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
			t.Fatalf("seed: %v: %s", err, s)
		}
	}
	return path
}

func TestOpen_VerifiesSchema(t *testing.T) {
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()
	if db.Read() == nil || db.Write() == nil {
		t.Fatalf("expected non-nil read/write handles")
	}
}

func TestOpen_FailsOnMissingSchema(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "empty.db")
	conn, _ := sql.Open("sqlite", "file:"+path)
	conn.Exec(`CREATE TABLE docker_hosts (id TEXT PRIMARY KEY)`)
	conn.Close()
	_, err := Open(path)
	if err == nil {
		t.Fatalf("expected schema verification error")
	}
}

func TestOpen_WriteHandleSerializesWrites(t *testing.T) {
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	stats := db.Write().Stats()
	if stats.MaxOpenConnections != 1 {
		t.Errorf("write MaxOpenConnections=%d, want 1", stats.MaxOpenConnections)
	}
}

func TestOpen_ReadHandleIsReadOnly(t *testing.T) {
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	_, err = db.Read().ExecContext(context.Background(),
		`INSERT INTO docker_hosts (id, name) VALUES ('x','y')`)
	if err == nil {
		t.Fatal("expected error: read handle should be read-only")
	}
}
