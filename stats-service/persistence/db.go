// Package persistence owns the stats-service side of the cross-process
// SQLite contract described in
// docs/superpowers/specs/2026-04-07-stats-persistence-design.md §8.
//
// It provides a DB handle with a single-connection write pool, a
// multi-connection read-only pool, and schema verification that fails
// fast if Alembic migration 037 has not been applied.
package persistence

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

// DB owns two sql.DB handles: a single-conn write pool and a multi-conn
// read pool. See spec §8.
type DB struct {
	write *sql.DB
	read  *sql.DB

	tokenMu    sync.RWMutex
	tokenCache map[string]tokenCacheEntry
}

type tokenCacheEntry struct {
	hostID string
	expiry time.Time
}

// buildDSN returns a SQLite URI DSN for dbPath with the given raw query
// parameters (pre-formatted "key=value" strings). Using net/url for the
// path ensures dbPaths containing '?', '#', '%', or spaces are correctly
// percent-encoded: the modernc.org/sqlite driver splits the DSN on the
// first '?' (see driver's newConn), so a raw fmt.Sprintf would silently
// open a file at the wrong location if the path ever contained '?'.
//
// Params are joined manually rather than via url.Values because pragma
// values like "journal_mode(WAL)" contain parentheses that url.Values
// would percent-encode, which the driver's pragma parser does not accept.
func buildDSN(dbPath string, params []string) string {
	u := url.URL{
		Scheme:   "file",
		Path:     dbPath,
		RawQuery: strings.Join(params, "&"),
	}
	return u.String()
}

// Open opens dockmon.db with the appropriate pragmas for stats-service.
// The schema must already exist; Alembic owns CREATE TABLE.
func Open(dbPath string) (*DB, error) {
	commonPragmas := []string{
		"_pragma=journal_mode(WAL)",
		"_pragma=synchronous(NORMAL)",
		"_pragma=foreign_keys(on)",
	}

	writeDSN := buildDSN(dbPath, slices.Concat(commonPragmas, []string{
		"_pragma=busy_timeout(30000)",
		"_txlock=immediate",
	}))
	write, err := sql.Open("sqlite", writeDSN)
	if err != nil {
		return nil, fmt.Errorf("open write pool: %w", err)
	}
	write.SetMaxOpenConns(1)
	write.SetMaxIdleConns(1)

	readDSN := buildDSN(dbPath, slices.Concat(commonPragmas, []string{
		"_pragma=busy_timeout(5000)",
		"mode=ro",
	}))
	read, err := sql.Open("sqlite", readDSN)
	if err != nil {
		return nil, errors.Join(fmt.Errorf("open read pool: %w", err), write.Close())
	}
	read.SetMaxOpenConns(8)
	// Match idle to open so the pool does not churn connections under
	// steady read load. The default MaxIdleConns is 2.
	read.SetMaxIdleConns(8)

	db := &DB{
		write:      write,
		read:       read,
		tokenCache: make(map[string]tokenCacheEntry),
	}
	if err := db.verifySchema(); err != nil {
		return nil, errors.Join(err, db.Close())
	}
	return db, nil
}

// Read returns the read-only connection pool.
func (db *DB) Read() *sql.DB { return db.read }

// Write returns the single-connection write pool.
func (db *DB) Write() *sql.DB { return db.write }

// Close releases both pools, joining any errors from each close.
func (db *DB) Close() error {
	return errors.Join(db.write.Close(), db.read.Close())
}

// ErrInvalidAgentToken is returned when ValidateAgentToken doesn't recognize a token.
var ErrInvalidAgentToken = errors.New("invalid agent token")

const agentTokenCacheTTL = 5 * time.Minute

// ValidateAgentToken returns the host_id owning the given agent token.
// Looks up the in-memory cache first; on miss, queries the agents table.
//
// The agents.id column IS the token (see backend/agent/manager.py:140
// validate_permanent_token). We additionally project host_id and bind it
// to the WebSocket connection so a compromised agent cannot lie about
// which host it belongs to.
func (db *DB) ValidateAgentToken(ctx context.Context, token string) (string, error) {
	if token == "" {
		return "", ErrInvalidAgentToken
	}
	now := time.Now()

	db.tokenMu.RLock()
	if e, ok := db.tokenCache[token]; ok && now.Before(e.expiry) {
		db.tokenMu.RUnlock()
		return e.hostID, nil
	}
	db.tokenMu.RUnlock()

	var hostID string
	err := db.read.QueryRowContext(ctx,
		`SELECT host_id FROM agents WHERE id = ?`, token,
	).Scan(&hostID)
	if errors.Is(err, sql.ErrNoRows) {
		return "", ErrInvalidAgentToken
	}
	if err != nil {
		return "", fmt.Errorf("validate agent token: %w", err)
	}

	db.tokenMu.Lock()
	db.tokenCache[token] = tokenCacheEntry{hostID: hostID, expiry: now.Add(agentTokenCacheTTL)}
	db.tokenMu.Unlock()
	return hostID, nil
}

// InvalidateAgentToken evicts a token from the in-memory cache. The Python
// backend calls this via POST /api/agents/invalidate when an agent is deleted.
func (db *DB) InvalidateAgentToken(token string) {
	db.tokenMu.Lock()
	delete(db.tokenCache, token)
	db.tokenMu.Unlock()
}

// HistoryRow is a single retrieved bucket from one of the history tables.
// Pointer fields are nullable: nil means SQL NULL, which the gap-fill renders
// as a chart gap.
type HistoryRow struct {
	Timestamp      int64 // unix seconds
	CPU            *float64
	MemPercent     *float64
	MemUsed        *int64
	MemLimit       *int64
	NetBps         *float64
	ContainerCount *int // host-only
}

// QueryContainerHistory returns rows for one container in [fromUnix, toUnix]
// inclusive, ordered ascending by timestamp.
//
// memory_percent is derived in SQL from memory_usage / memory_limit so the
// read path produces a unified `mem` percent column for both containers and
// hosts. The container schema stores only absolute bytes (§6); computing the
// percent here keeps FillGaps tier-agnostic and lets the Task 14 handler
// serialize HistoryResponse without special-casing container vs host.
// NULLIF guards against divide-by-zero when memory_limit is 0 or NULL.
func (db *DB) QueryContainerHistory(
	ctx context.Context, containerID, resolution string, fromUnix, toUnix int64,
) ([]HistoryRow, error) {
	q := `SELECT timestamp,
	             cpu_percent,
	             (100.0 * memory_usage / NULLIF(memory_limit, 0)) AS memory_percent,
	             memory_usage,
	             memory_limit,
	             network_bps
	      FROM container_stats_history
	      WHERE container_id = ? AND resolution = ?
	        AND timestamp >= ? AND timestamp <= ?
	      ORDER BY timestamp ASC`
	rows, err := db.read.QueryContext(ctx, q, containerID, resolution, fromUnix, toUnix)
	if err != nil {
		return nil, fmt.Errorf("query container history: %w", err)
	}
	defer rows.Close()
	var out []HistoryRow
	for rows.Next() {
		var r HistoryRow
		if err := rows.Scan(
			&r.Timestamp, &r.CPU, &r.MemPercent, &r.MemUsed, &r.MemLimit, &r.NetBps,
		); err != nil {
			return nil, fmt.Errorf("scan container history: %w", err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// QueryHostHistory returns rows for one host in [fromUnix, toUnix].
func (db *DB) QueryHostHistory(
	ctx context.Context, hostID, resolution string, fromUnix, toUnix int64,
) ([]HistoryRow, error) {
	q := `SELECT timestamp, cpu_percent, memory_percent, memory_used_bytes,
	             memory_limit_bytes, network_bps, container_count
	      FROM host_stats_history
	      WHERE host_id = ? AND resolution = ?
	        AND timestamp >= ? AND timestamp <= ?
	      ORDER BY timestamp ASC`
	rows, err := db.read.QueryContext(ctx, q, hostID, resolution, fromUnix, toUnix)
	if err != nil {
		return nil, fmt.Errorf("query host history: %w", err)
	}
	defer rows.Close()
	var out []HistoryRow
	for rows.Next() {
		var r HistoryRow
		if err := rows.Scan(
			&r.Timestamp, &r.CPU, &r.MemPercent, &r.MemUsed,
			&r.MemLimit, &r.NetBps, &r.ContainerCount,
		); err != nil {
			return nil, fmt.Errorf("scan host history: %w", err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// verifySchema fails if Alembic has not applied migration 037.
//
// The query runs through the write pool so the first connection to a
// fresh SQLite file can upgrade journal_mode to WAL; a mode=ro handle
// cannot perform that upgrade. This also guarantees the DB is in WAL
// mode by the time the read pool opens its first connection.
func (db *DB) verifySchema() error {
	required := []string{"container_stats_history", "host_stats_history"}
	for _, table := range required {
		var name string
		err := db.write.QueryRow(
			`SELECT name FROM sqlite_master WHERE type='table' AND name = ?`,
			table,
		).Scan(&name)
		if errors.Is(err, sql.ErrNoRows) {
			return fmt.Errorf("schema verification failed: table %q missing - has Alembic migration 037 run?", table)
		}
		if err != nil {
			return fmt.Errorf("schema verification: %w", err)
		}
	}
	return nil
}
