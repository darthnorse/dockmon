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
		maxPoints := r.maxPointsForTier(tier)

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
			)`, tier.Name, maxPoints)
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
			)`, tier.Name, maxPoints)
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

// RunTimeSweep deletes rows older than max(retentionDays, longestTierWindow).
// Returns total rows deleted across both history tables.
//
// The cutoff is floored at the longest tier window so we never delete buckets
// the cascade is still actively writing to.
func (r *Retention) RunTimeSweep(ctx context.Context, retentionDays int) (int64, error) {
	start := time.Now()

	cutoffDuration := time.Duration(retentionDays) * 24 * time.Hour
	for _, t := range r.tiers {
		if t.Window > cutoffDuration {
			cutoffDuration = t.Window
		}
	}
	cutoff := time.Now().Add(-cutoffDuration).Unix()

	res, err := r.db.write.ExecContext(ctx,
		`DELETE FROM container_stats_history WHERE timestamp < ?`, cutoff)
	if err != nil {
		return 0, fmt.Errorf("time sweep container: %w", err)
	}
	c, _ := res.RowsAffected()

	res, err = r.db.write.ExecContext(ctx,
		`DELETE FROM host_stats_history WHERE timestamp < ?`, cutoff)
	if err != nil {
		return c, fmt.Errorf("time sweep host: %w", err)
	}
	h, _ := res.RowsAffected()

	total := c + h
	log.Printf("Time sweep: deleted %d rows older than %v, took %v",
		total, cutoffDuration, time.Since(start))
	return total, nil
}

// SettingsProvider lets Retention read the current retention_days at run time
// without tightly coupling to the rest of stats-service. The main package
// supplies an implementation that reads from in-memory config (Task 15).
type SettingsProvider interface {
	RetentionDays() int
}

// Run is the long-lived scheduling loop. Fires ring buffer hourly and time
// sweep daily until ctx is done.
func (r *Retention) Run(ctx context.Context, settings SettingsProvider) {
	ringTicker := time.NewTicker(1 * time.Hour)
	defer ringTicker.Stop()
	sweepTicker := time.NewTicker(24 * time.Hour)
	defer sweepTicker.Stop()

	log.Println("Retention scheduler started: ring buffer hourly, time sweep daily")
	for {
		select {
		case <-ctx.Done():
			log.Println("Retention scheduler stopped")
			return
		case <-ringTicker.C:
			if err := r.RunRingBuffer(ctx); err != nil {
				log.Printf("Retention: ring buffer error: %v", err)
			}
		case <-sweepTicker.C:
			if _, err := r.RunTimeSweep(ctx, settings.RetentionDays()); err != nil {
				log.Printf("Retention: time sweep error: %v", err)
			}
		}
	}
}
