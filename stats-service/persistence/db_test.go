package persistence

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"testing"
)

// makeFixtureDB creates a sqlite file in a fresh temp dir with the
// schema this package expects (what Alembic would create in production).
func makeFixtureDB(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "test.db")
	seedFixture(t, path)
	return path
}

// seedFixture applies the expected schema at the given path. Separated
// from makeFixtureDB so tests needing a specific path (e.g. URI-special
// characters) can reuse the seed SQL.
func seedFixture(t *testing.T, path string) {
	t.Helper()
	conn, err := sql.Open("sqlite", buildDSN(path, nil))
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer func() {
		if err := conn.Close(); err != nil {
			t.Errorf("close seed conn: %v", err)
		}
	}()
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
	path := filepath.Join(t.TempDir(), "empty.db")
	conn, err := sql.Open("sqlite", buildDSN(path, nil))
	if err != nil {
		t.Fatalf("sql.Open: %v", err)
	}
	if _, err := conn.Exec(`CREATE TABLE docker_hosts (id TEXT PRIMARY KEY)`); err != nil {
		t.Fatalf("seed: %v", err)
	}
	if err := conn.Close(); err != nil {
		t.Fatalf("close seed: %v", err)
	}
	if _, err := Open(path); err == nil {
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

// TestOpen_PathWithURISpecialChars guards against DSN path-escaping
// regressions. If Open ever drops net/url and falls back to fmt.Sprintf,
// the driver will split on the first '?' in dbPath and open a file at
// the wrong location.
func TestOpen_PathWithURISpecialChars(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "dir with ? # % chars")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	path := filepath.Join(dir, "test.db")
	seedFixture(t, path)

	db, err := Open(path)
	if err != nil {
		t.Fatalf("Open with special chars in path: %v", err)
	}
	t.Cleanup(func() {
		if err := db.Close(); err != nil {
			t.Errorf("Close: %v", err)
		}
	})

	// Confirm the write pool targets the intended file, not a stray
	// file at a truncated path.
	if _, err := db.Write().Exec(`INSERT INTO docker_hosts (id, name) VALUES ('h1', 'host1')`); err != nil {
		t.Fatalf("write to special-char path: %v", err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat expected db file: %v", err)
	}
	if info.Size() == 0 {
		t.Fatalf("expected non-empty db file at %q", path)
	}
}
