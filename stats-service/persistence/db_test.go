package persistence

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// makeFixtureDB creates a sqlite file in a fresh temp dir with the
// schema this package expects (what Alembic would create in production).
// Delegates to MakeFixtureDBForTest so the same seed is reused by handler
// tests in the parent stats-service package.
func makeFixtureDB(t *testing.T) string {
	return MakeFixtureDBForTest(t)
}

// seedFixture applies the expected schema at the given path. Separated from
// makeFixtureDB so tests needing a specific path (e.g. URI-special characters)
// can seed it directly.
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
	for _, s := range fixtureSchemaSQL {
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

// openWithSeededAgent returns a DB with a single docker_hosts row and a
// single agents row pre-inserted, plus a t.Cleanup for Close. Used by
// ValidateAgentToken tests to cut fixture boilerplate.
func openWithSeededAgent(t *testing.T, token, hostID string) *DB {
	t.Helper()
	db, err := Open(makeFixtureDB(t))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := db.Close(); err != nil {
			t.Errorf("close: %v", err)
		}
	})
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id, name) VALUES (?, ?)`, hostID, hostID); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(
		`INSERT INTO agents (id, host_id) VALUES (?, ?)`, token, hostID); err != nil {
		t.Fatal(err)
	}
	return db
}

func TestValidateAgentToken_Valid(t *testing.T) {
	db := openWithSeededAgent(t, "token-abc", "host-1")
	hostID, err := db.ValidateAgentToken(context.Background(), "token-abc")
	if err != nil {
		t.Fatalf("ValidateAgentToken: %v", err)
	}
	if hostID != "host-1" {
		t.Errorf("hostID=%q, want host-1", hostID)
	}
}

func TestValidateAgentToken_Invalid(t *testing.T) {
	db, err := Open(makeFixtureDB(t))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	_, err = db.ValidateAgentToken(context.Background(), "nope")
	if !errors.Is(err, ErrInvalidAgentToken) {
		t.Errorf("err=%v, want ErrInvalidAgentToken", err)
	}
}

func TestValidateAgentToken_EmptyToken(t *testing.T) {
	db, err := Open(makeFixtureDB(t))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	_, err = db.ValidateAgentToken(context.Background(), "")
	if !errors.Is(err, ErrInvalidAgentToken) {
		t.Errorf("empty token: err=%v, want ErrInvalidAgentToken", err)
	}
}

func TestValidateAgentToken_CacheHit(t *testing.T) {
	db := openWithSeededAgent(t, "tok", "host-1")
	if _, err := db.ValidateAgentToken(context.Background(), "tok"); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(`DELETE FROM agents WHERE id = 'tok'`); err != nil {
		t.Fatal(err)
	}
	hostID, err := db.ValidateAgentToken(context.Background(), "tok")
	if err != nil {
		t.Fatalf("expected cache hit, got %v", err)
	}
	if hostID != "host-1" {
		t.Errorf("got %q, want host-1", hostID)
	}
}

func TestValidateAgentToken_CacheExpiry(t *testing.T) {
	db := openWithSeededAgent(t, "tok", "host-1")
	if _, err := db.ValidateAgentToken(context.Background(), "tok"); err != nil {
		t.Fatal(err)
	}

	// Force the cached entry to be expired, then delete the row so a
	// stale cache hit would return the wrong answer. A correct TTL check
	// must refuse the cached entry, re-query, miss, and return
	// ErrInvalidAgentToken.
	db.tokenMu.Lock()
	entry := db.tokenCache["tok"]
	entry.expiry = time.Now().Add(-time.Second)
	db.tokenCache["tok"] = entry
	db.tokenMu.Unlock()

	if _, err := db.Write().Exec(`DELETE FROM agents WHERE id = 'tok'`); err != nil {
		t.Fatal(err)
	}

	_, err := db.ValidateAgentToken(context.Background(), "tok")
	if !errors.Is(err, ErrInvalidAgentToken) {
		t.Errorf("expired entry should not satisfy lookup: err=%v, want ErrInvalidAgentToken", err)
	}
}

func TestInvalidateAgentToken(t *testing.T) {
	db := openWithSeededAgent(t, "tok", "host-1")
	if _, err := db.ValidateAgentToken(context.Background(), "tok"); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(`DELETE FROM agents WHERE id = 'tok'`); err != nil {
		t.Fatal(err)
	}
	db.InvalidateAgentToken("tok")
	_, err := db.ValidateAgentToken(context.Background(), "tok")
	if !errors.Is(err, ErrInvalidAgentToken) {
		t.Errorf("after invalidate, expected ErrInvalidAgentToken, got %v", err)
	}
}

func TestQueryContainerHistory_ReturnsRows(t *testing.T) {
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(`INSERT INTO docker_hosts (id,name) VALUES ('h1','h1')`); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		if _, err := db.Write().Exec(`INSERT INTO container_stats_history
			(container_id, host_id, timestamp, resolution, cpu_percent, memory_usage, memory_limit, network_bps)
			VALUES (?,?,?,?,?,?,?,?)`,
			"h1:abc123abc123", "h1", int64(1_000_000+i*10), "1h",
			float64(i), int64(i*100), int64(8192), float64(i*1000)); err != nil {
			t.Fatal(err)
		}
	}

	rows, err := db.QueryContainerHistory(
		context.Background(),
		"h1:abc123abc123", "1h", 1_000_010, 1_000_030,
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 3 {
		t.Fatalf("got %d rows, want 3", len(rows))
	}
	// Verify memory_percent is computed from usage/limit. Row 0 in the
	// result corresponds to i=1 (timestamp 1_000_010): memory_usage=100,
	// memory_limit=8192, expected percent = 100 * 100 / 8192 ≈ 1.2207.
	if rows[0].MemPercent == nil {
		t.Fatal("MemPercent is nil, want computed value")
	}
	wantPct := 100.0 * 100.0 / 8192.0
	if diff := *rows[0].MemPercent - wantPct; diff > 0.0001 || diff < -0.0001 {
		t.Errorf("MemPercent[0]=%v, want %v", *rows[0].MemPercent, wantPct)
	}
	// Absolute bytes are still populated for the modal display.
	if rows[0].MemUsed == nil || *rows[0].MemUsed != 100 {
		t.Errorf("MemUsed[0]=%v, want 100", rows[0].MemUsed)
	}
	if rows[0].MemLimit == nil || *rows[0].MemLimit != 8192 {
		t.Errorf("MemLimit[0]=%v, want 8192", rows[0].MemLimit)
	}
}

func TestQueryContainerHistory_EmptyResult(t *testing.T) {
	// No rows in the table — the query should return an empty slice (not an
	// error) so the handler can gap-fill a pure-null response.
	db, err := Open(makeFixtureDB(t))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })

	rows, err := db.QueryContainerHistory(
		context.Background(), "h1:nonexistent1", "1h", 0, 9_999_999,
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 0 {
		t.Errorf("got %d rows, want 0", len(rows))
	}
}

func TestQueryContainerHistory_NullMemoryLimit(t *testing.T) {
	// memory_limit=0 must NOT divide-by-zero; NULLIF turns it into SQL NULL
	// which scans as a nil *float64 — rendered as a chart gap downstream.
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(`INSERT INTO docker_hosts (id,name) VALUES ('h1','h1')`); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(`INSERT INTO container_stats_history
		(container_id, host_id, timestamp, resolution, cpu_percent, memory_usage, memory_limit, network_bps)
		VALUES (?,?,?,?,?,?,?,?)`,
		"h1:abc123abc123", "h1", int64(2_000_000), "1h",
		float64(42), int64(1024), int64(0), float64(0)); err != nil {
		t.Fatal(err)
	}

	rows, err := db.QueryContainerHistory(
		context.Background(), "h1:abc123abc123", "1h", 2_000_000, 2_000_000,
	)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 {
		t.Fatalf("got %d rows, want 1", len(rows))
	}
	if rows[0].MemPercent != nil {
		t.Errorf("MemPercent=%v, want nil (memory_limit=0 → NULL)", *rows[0].MemPercent)
	}
}

func TestQueryHostHistory_ReturnsRows(t *testing.T) {
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(`INSERT INTO docker_hosts (id,name) VALUES ('h1','h1')`); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		if _, err := db.Write().Exec(`INSERT INTO host_stats_history
			(host_id, timestamp, resolution, cpu_percent, memory_percent,
			 memory_used_bytes, memory_limit_bytes, network_bps, container_count)
			VALUES (?,?,?,?,?,?,?,?,?)`,
			"h1", int64(1_000_000+i*10), "1h",
			float64(i*10), float64(i*5),
			int64(1<<30), int64(8<<30), float64(i*100), i+1); err != nil {
			t.Fatal(err)
		}
	}

	rows, err := db.QueryHostHistory(
		context.Background(), "h1", "1h", 1_000_000, 1_000_020)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 3 {
		t.Errorf("got %d rows, want 3", len(rows))
	}
}

func TestLoadGlobalSettings_DefaultRow(t *testing.T) {
	db, err := Open(makeFixtureDB(t))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })

	s, err := db.LoadGlobalSettings(context.Background())
	if err != nil {
		t.Fatalf("LoadGlobalSettings: %v", err)
	}
	if s == nil {
		t.Fatal("expected settings, got nil (fixture seeds id=1)")
	}
	if s.PersistEnabled {
		t.Errorf("PersistEnabled=true, want false (DDL default 0)")
	}
	if s.RetentionDays != 30 {
		t.Errorf("RetentionDays=%d, want 30", s.RetentionDays)
	}
	if s.PointsPerView != 500 {
		t.Errorf("PointsPerView=%d, want 500", s.PointsPerView)
	}
}

func TestLoadGlobalSettings_UserOptedIn(t *testing.T) {
	db, err := Open(makeFixtureDB(t))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })

	if _, err := db.Write().Exec(
		`UPDATE global_settings
		 SET stats_persistence_enabled = 1,
		     stats_retention_days = 14,
		     stats_points_per_view = 1000
		 WHERE id = 1`); err != nil {
		t.Fatal(err)
	}

	s, err := db.LoadGlobalSettings(context.Background())
	if err != nil {
		t.Fatalf("LoadGlobalSettings: %v", err)
	}
	if !s.PersistEnabled || s.RetentionDays != 14 || s.PointsPerView != 1000 {
		t.Errorf("got %+v, want {true 14 1000}", *s)
	}
}

func TestLoadGlobalSettings_NoRow(t *testing.T) {
	db, err := Open(makeFixtureDB(t))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { db.Close() })

	if _, err := db.Write().Exec(`DELETE FROM global_settings WHERE id = 1`); err != nil {
		t.Fatal(err)
	}

	s, err := db.LoadGlobalSettings(context.Background())
	if err != nil {
		t.Fatalf("LoadGlobalSettings: %v", err)
	}
	if s != nil {
		t.Errorf("got %+v, want nil (no row)", *s)
	}
}
