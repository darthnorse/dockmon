package persistence

import (
	"context"
	"fmt"
	"log"
	"time"
)

// Retention owns the periodic cleanup tickers: ring buffer (hourly) and
// time sweep (daily). See spec §11.
type Retention struct {
	db    *DB
	tiers []Tier
}

// NewRetention constructs a retention manager.
func NewRetention(db *DB, tiers []Tier) *Retention {
	return &Retention{db: db, tiers: tiers}
}

// maxPointsForTier returns the maximum bucket count each (entity, tier)
// series is allowed to keep. At the default points_per_view=500 with
// the 1s interval floor, every tier holds 500 points.
func (r *Retention) maxPointsForTier(t Tier) int {
	return int(t.Window / t.Interval)
}

// RunRingBuffer trims each (entity, resolution) bucket series down to
// maxPointsForTier rows, keeping the newest. One bulk DELETE per (table, tier).
//
// Per spec §17 risk #4, this MUST use the window-function form, not the
// per-entity nested-SELECT form. SQLite 3.25+ supports ROW_NUMBER() natively.
// At 700 containers × 5 tiers, naive per-entity queries would run 3500+ times
// per cleanup cycle; the window-function form runs 10 queries total.
func (r *Retention) RunRingBuffer(ctx context.Context) error {
	start := time.Now()
	var totalDeleted int64

	for _, tier := range r.tiers {
		max := r.maxPointsForTier(tier)

		res, err := r.db.write.ExecContext(ctx, `
			DELETE FROM container_stats_history
			WHERE id IN (
				SELECT id FROM (
					SELECT id, ROW_NUMBER() OVER (
						PARTITION BY container_id
						ORDER BY timestamp DESC
					) AS rn
					FROM container_stats_history
					WHERE resolution = ?
				) WHERE rn > ?
			)`, tier.Name, max)
		if err != nil {
			return fmt.Errorf("ring buffer container tier %s: %w", tier.Name, err)
		}
		n, _ := res.RowsAffected()
		totalDeleted += n

		res, err = r.db.write.ExecContext(ctx, `
			DELETE FROM host_stats_history
			WHERE id IN (
				SELECT id FROM (
					SELECT id, ROW_NUMBER() OVER (
						PARTITION BY host_id
						ORDER BY timestamp DESC
					) AS rn
					FROM host_stats_history
					WHERE resolution = ?
				) WHERE rn > ?
			)`, tier.Name, max)
		if err != nil {
			return fmt.Errorf("ring buffer host tier %s: %w", tier.Name, err)
		}
		n, _ = res.RowsAffected()
		totalDeleted += n
	}

	log.Printf("Ring buffer: deleted %d rows, took %v",
		totalDeleted, time.Since(start))
	return nil
}
