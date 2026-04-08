package persistence

import (
	"context"
	"fmt"
	"log"
	"math"
	"strings"
	"time"
)

const (
	writerBatchSize  = 256
	writerFlushEvery = 1 * time.Second
)

// Writer drains writeJobs from a channel into batched SQL transactions.
// A single Writer uses db.Write() (single-connection pool) so writes are
// naturally serialized at the database level.
type Writer struct {
	db   *DB
	jobs <-chan writeJob
}

// NewWriter constructs a writer. Call Run in a goroutine.
func NewWriter(db *DB, jobs <-chan writeJob) *Writer {
	return &Writer{db: db, jobs: jobs}
}

// Run drains the channel until ctx is done. Flushes at writerBatchSize jobs,
// at writerFlushEvery cadence, and once more on context cancellation.
func (w *Writer) Run(ctx context.Context) {
	batch := make([]writeJob, 0, writerBatchSize)
	ticker := time.NewTicker(writerFlushEvery)
	defer ticker.Stop()

	flush := func() {
		if len(batch) == 0 {
			return
		}
		if err := w.commitBatch(batch); err != nil {
			log.Printf("Writer: commit failed: %v (batch size %d)", err, len(batch))
		}
		batch = batch[:0]
	}

	for {
		select {
		case <-ctx.Done():
			flush()
			return
		case j := <-w.jobs:
			batch = append(batch, j)
			if len(batch) >= writerBatchSize {
				flush()
			}
		case <-ticker.C:
			flush()
		}
	}
}

func (w *Writer) commitBatch(batch []writeJob) error {
	tx, err := w.db.write.Begin()
	if err != nil {
		return fmt.Errorf("begin: %w", err)
	}
	defer tx.Rollback() //nolint:errcheck // no-op after Commit

	containerStmt, err := tx.Prepare(`
		INSERT OR REPLACE INTO container_stats_history
		  (container_id, host_id, timestamp, resolution,
		   cpu_percent, memory_usage, memory_limit, network_bps)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`)
	if err != nil {
		return fmt.Errorf("prepare container insert: %w", err)
	}
	defer containerStmt.Close()

	hostStmt, err := tx.Prepare(`
		INSERT OR REPLACE INTO host_stats_history
		  (host_id, timestamp, resolution,
		   cpu_percent, memory_percent, memory_used_bytes, memory_limit_bytes,
		   network_bps, container_count)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`)
	if err != nil {
		return fmt.Errorf("prepare host insert: %w", err)
	}
	defer hostStmt.Close()

	for _, j := range batch {
		if j.isHost {
			if _, err := hostStmt.Exec(
				j.entityID, j.ts.Unix(), j.tier,
				nullIfNaN(j.value.CPU),
				nullIfNaN(j.value.MemPercent),
				nullIfZeroU64(j.value.MemUsed),
				nullIfZeroU64(j.value.MemLimit),
				nullIfNaN(j.value.NetBps),
				j.value.ContainerCount,
			); err != nil {
				return fmt.Errorf("host insert: %w", err)
			}
		} else {
			hostID, ok := splitCompositeKey(j.entityID)
			if !ok {
				return fmt.Errorf("invalid composite key %q", j.entityID)
			}
			if _, err := containerStmt.Exec(
				j.entityID, hostID, j.ts.Unix(), j.tier,
				nullIfNaN(j.value.CPU),
				nullIfZeroU64(j.value.MemUsed),
				nullIfZeroU64(j.value.MemLimit),
				nullIfNaN(j.value.NetBps),
			); err != nil {
				return fmt.Errorf("container insert: %w", err)
			}
		}
	}
	if err := tx.Commit(); err != nil {
		return fmt.Errorf("commit: %w", err)
	}
	return nil
}

// nullIfNaN returns nil for NaN so database/sql stores SQL NULL. Empty buckets
// blend to NaN per cascade.go's blend function.
func nullIfNaN(f float64) interface{} {
	if math.IsNaN(f) {
		return nil
	}
	return f
}

// nullIfZeroU64 returns nil for zero so database/sql stores SQL NULL.
// Memory usage or limit of 0 invariably means "no data" at DockMon's scale,
// not "literally zero bytes."
func nullIfZeroU64(v uint64) interface{} {
	if v == 0 {
		return nil
	}
	return int64(v)
}

// splitCompositeKey parses "host_id:container_id" into its host_id component.
// Returns ok=false if the key is malformed.
func splitCompositeKey(k string) (string, bool) {
	idx := strings.IndexByte(k, ':')
	if idx <= 0 || idx == len(k)-1 {
		return "", false
	}
	return k[:idx], true
}
