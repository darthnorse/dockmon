// Package persistence owns SQLite connection pools, schema verification,
// agent token validation, the in-memory cascade, the writer goroutine, and
// retention cleanup. See docs/superpowers/specs/2026-04-07-stats-persistence-design.md.
package persistence

import (
	"database/sql"
	"errors"
	"fmt"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

// DB owns two sql.DB handles: a single-conn write pool and a multi-conn read pool.
// See spec §8.
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

// Open opens dockmon.db with the appropriate pragmas for stats-service.
// The schema must already exist (Alembic owns CREATE TABLE).
func Open(dbPath string) (*DB, error) {
	writeDSN := fmt.Sprintf(
		"file:%s?_pragma=journal_mode(WAL)&_pragma=synchronous(NORMAL)"+
			"&_pragma=foreign_keys(on)&_pragma=busy_timeout(30000)"+
			"&_txlock=immediate",
		dbPath)
	write, err := sql.Open("sqlite", writeDSN)
	if err != nil {
		return nil, fmt.Errorf("open write: %w", err)
	}
	write.SetMaxOpenConns(1)
	write.SetMaxIdleConns(1)

	readDSN := fmt.Sprintf(
		"file:%s?_pragma=journal_mode(WAL)&_pragma=synchronous(NORMAL)"+
			"&_pragma=foreign_keys(on)&_pragma=busy_timeout(5000)&mode=ro",
		dbPath)
	read, err := sql.Open("sqlite", readDSN)
	if err != nil {
		write.Close()
		return nil, fmt.Errorf("open read: %w", err)
	}
	read.SetMaxOpenConns(8)

	db := &DB{
		write:      write,
		read:       read,
		tokenCache: make(map[string]tokenCacheEntry),
	}
	if err := db.verifySchema(); err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

// Read returns the read-only connection pool.
func (db *DB) Read() *sql.DB { return db.read }

// Write returns the single-connection write pool.
func (db *DB) Write() *sql.DB { return db.write }

// Close releases both pools.
func (db *DB) Close() error {
	var errs []error
	if err := db.write.Close(); err != nil {
		errs = append(errs, err)
	}
	if err := db.read.Close(); err != nil {
		errs = append(errs, err)
	}
	if len(errs) > 0 {
		return fmt.Errorf("close: %v", errs)
	}
	return nil
}

// verifySchema fails if Alembic hasn't applied migration 037.
// We check for the two history tables explicitly.
//
// We query through the write pool here, not the read pool. The first
// connection to touch a fresh DB file needs write capability in order to
// upgrade journal_mode to WAL; a mode=ro handle cannot perform that upgrade
// and would fail with "attempt to write a readonly database". Using the
// write pool also ensures the DB is in WAL mode by the time the read pool
// opens its first connection.
func (db *DB) verifySchema() error {
	required := []string{
		"container_stats_history",
		"host_stats_history",
	}
	for _, table := range required {
		var name string
		err := db.write.QueryRow(
			`SELECT name FROM sqlite_master WHERE type='table' AND name = ?`,
			table,
		).Scan(&name)
		if errors.Is(err, sql.ErrNoRows) {
			return fmt.Errorf("schema verification failed: table %q missing — has Alembic migration 037 run?", table)
		}
		if err != nil {
			return fmt.Errorf("schema verification: %w", err)
		}
	}
	return nil
}
