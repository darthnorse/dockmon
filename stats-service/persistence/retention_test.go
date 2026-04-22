package persistence

import (
	"context"
	"testing"
	"time"
)

func seedContainerRows(t *testing.T, db *DB, containerID, hostID, resolution string, n int) {
	t.Helper()
	for i := 0; i < n; i++ {
		_, err := db.Write().Exec(`
			INSERT INTO container_stats_history
			(container_id, host_id, timestamp, resolution, cpu_percent)
			VALUES (?, ?, ?, ?, ?)`,
			containerID, hostID, int64(1_000_000+i), resolution, float64(i))
		if err != nil {
			t.Fatal(err)
		}
	}
}

func seedHostRows(t *testing.T, db *DB, hostID, resolution string, n int) {
	t.Helper()
	for i := 0; i < n; i++ {
		_, err := db.Write().Exec(`
			INSERT INTO host_stats_history
			(host_id, timestamp, resolution, cpu_percent)
			VALUES (?, ?, ?, ?)`,
			hostID, int64(1_000_000+i), resolution, float64(i))
		if err != nil {
			t.Fatal(err)
		}
	}
}

func TestRingBuffer_TrimsContainerRowsToMaxPoints(t *testing.T) {
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(`INSERT INTO docker_hosts (id, name) VALUES ('h1','h1')`); err != nil {
		t.Fatal(err)
	}

	seedContainerRows(t, db, "h1:abc123abc123", "h1", "1h", 600)
	seedContainerRows(t, db, "h1:def456def456", "h1", "1h", 50)

	r := NewRetention(db, ComputeTiers(500))
	if err := r.RunRingBuffer(context.Background()); err != nil {
		t.Fatal(err)
	}

	var c1, c2 int
	if err := db.Read().QueryRow(
		`SELECT COUNT(*) FROM container_stats_history WHERE container_id = ?`,
		"h1:abc123abc123",
	).Scan(&c1); err != nil {
		t.Fatal(err)
	}
	if err := db.Read().QueryRow(
		`SELECT COUNT(*) FROM container_stats_history WHERE container_id = ?`,
		"h1:def456def456",
	).Scan(&c2); err != nil {
		t.Fatal(err)
	}
	if c1 != 500 {
		t.Errorf("c1 rows=%d, want 500", c1)
	}
	if c2 != 50 {
		t.Errorf("c2 rows=%d, want 50 (under limit, untouched)", c2)
	}

	// Confirm OLDEST rows were deleted, not newest.
	var minTs int64
	if err := db.Read().QueryRow(
		`SELECT MIN(timestamp) FROM container_stats_history WHERE container_id = ?`,
		"h1:abc123abc123",
	).Scan(&minTs); err != nil {
		t.Fatal(err)
	}
	if minTs != 1_000_100 {
		t.Errorf("min ts=%d, want 1_000_100 (oldest 100 deleted)", minTs)
	}
}

func TestRingBuffer_TrimsHostRows(t *testing.T) {
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(`INSERT INTO docker_hosts (id, name) VALUES ('h1','h1')`); err != nil {
		t.Fatal(err)
	}

	seedHostRows(t, db, "h1", "1h", 600)

	r := NewRetention(db, ComputeTiers(500))
	if err := r.RunRingBuffer(context.Background()); err != nil {
		t.Fatal(err)
	}

	var n int
	if err := db.Read().QueryRow(`SELECT COUNT(*) FROM host_stats_history`).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 500 {
		t.Errorf("got %d rows, want 500", n)
	}
}

func TestRingBuffer_EmptyDatabase(t *testing.T) {
	// Edge case from spec §15: empty tier. Running against a schema with no
	// rows must complete cleanly and delete nothing, not error on the window
	// function or on RowsAffected.
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })

	r := NewRetention(db, ComputeTiers(500))
	if err := r.RunRingBuffer(context.Background()); err != nil {
		t.Fatalf("empty-db ring buffer failed: %v", err)
	}

	var c, h int
	if err := db.Read().QueryRow(`SELECT COUNT(*) FROM container_stats_history`).Scan(&c); err != nil {
		t.Fatal(err)
	}
	if err := db.Read().QueryRow(`SELECT COUNT(*) FROM host_stats_history`).Scan(&h); err != nil {
		t.Fatal(err)
	}
	if c != 0 || h != 0 {
		t.Errorf("empty-db rows after run: container=%d host=%d, want 0/0", c, h)
	}
}

func TestRingBuffer_RespectsTierMaxPoints(t *testing.T) {
	// At points_per_view=500, all tiers hold exactly 500 max points.
	tiers := ComputeTiers(500)
	r := &Retention{tiers: tiers}
	for _, tier := range tiers {
		got := r.maxPointsForTier(tier)
		if got != 500 {
			t.Errorf("tier %s max points=%d, want 500", tier.Name, got)
		}
	}
}

func TestRingBuffer_MultipleContainersMultipleTiers(t *testing.T) {
	// Regression test: two containers at two different tiers. Each (container, tier)
	// pair should be trimmed independently. This exercises the PARTITION BY clause.
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(`INSERT INTO docker_hosts (id, name) VALUES ('h1','h1')`); err != nil {
		t.Fatal(err)
	}

	seedContainerRows(t, db, "h1:c1", "h1", "1h", 600)
	seedContainerRows(t, db, "h1:c2", "h1", "1h", 700)
	seedContainerRows(t, db, "h1:c1", "h1", "8h", 550)
	seedContainerRows(t, db, "h1:c2", "h1", "8h", 400)

	r := NewRetention(db, ComputeTiers(500))
	if err := r.RunRingBuffer(context.Background()); err != nil {
		t.Fatal(err)
	}

	expected := map[string]map[string]int{
		"h1:c1": {"1h": 500, "8h": 500},
		"h1:c2": {"1h": 500, "8h": 400},
	}
	for cid, tierCounts := range expected {
		for tier, want := range tierCounts {
			var got int
			if err := db.Read().QueryRow(
				`SELECT COUNT(*) FROM container_stats_history WHERE container_id = ? AND resolution = ?`,
				cid, tier,
			).Scan(&got); err != nil {
				t.Fatal(err)
			}
			if got != want {
				t.Errorf("%s tier %s: got %d rows, want %d", cid, tier, got, want)
			}
		}
	}
}

func TestTimeSweep_DeletesOldRows(t *testing.T) {
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id, name) VALUES ('h1','h1')`); err != nil {
		t.Fatal(err)
	}

	now := time.Now().Unix()
	// "old" must exceed the longest tier window (now 30d). The time sweep
	// floors the cutoff to max(retentionDays, longestTierWindow), so rows
	// within 30 days are always kept regardless of retentionDays.
	old := now - int64((45 * 24 * time.Hour).Seconds())  // 45 days ago
	fresh := now - int64((10 * 24 * time.Hour).Seconds()) // 10 days ago

	if _, err := db.Write().Exec(`INSERT INTO container_stats_history
		(container_id, host_id, timestamp, resolution, cpu_percent)
		VALUES (?, ?, ?, ?, ?)`,
		"h1:abc123abc123", "h1", old, "1h", 1.0); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(`INSERT INTO container_stats_history
		(container_id, host_id, timestamp, resolution, cpu_percent)
		VALUES (?, ?, ?, ?, ?)`,
		"h1:abc123abc123", "h1", fresh, "1h", 2.0); err != nil {
		t.Fatal(err)
	}
	if _, err := db.Write().Exec(`INSERT INTO host_stats_history
		(host_id, timestamp, resolution, cpu_percent)
		VALUES (?, ?, ?, ?)`,
		"h1", old, "30d", 1.0); err != nil {
		t.Fatal(err)
	}

	r := NewRetention(db, ComputeTiers(500))
	deleted, err := r.RunTimeSweep(context.Background(), 30)
	if err != nil {
		t.Fatal(err)
	}
	if deleted != 2 {
		t.Errorf("deleted=%d, want 2 (one container row, one host row)", deleted)
	}

	var n int
	if err := db.Read().QueryRow(
		`SELECT COUNT(*) FROM container_stats_history WHERE container_id = ?`,
		"h1:abc123abc123",
	).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Errorf("fresh row count=%d, want 1", n)
	}
}

func TestTimeSweep_FloorsCutoffToLongestTierWindow(t *testing.T) {
	// If user sets retention_days=5 but the longest tier is 30 days, the
	// effective cutoff must NOT be 5 days — that would delete the 7d/30d
	// tiers' working data.
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id, name) VALUES ('h1','h1')`); err != nil {
		t.Fatal(err)
	}

	now := time.Now().Unix()
	day10 := now - int64((10 * 24 * time.Hour).Seconds())
	if _, err := db.Write().Exec(`INSERT INTO host_stats_history
		(host_id, timestamp, resolution, cpu_percent)
		VALUES (?, ?, ?, ?)`,
		"h1", day10, "30d", 1.0); err != nil {
		t.Fatal(err)
	}

	r := NewRetention(db, ComputeTiers(500))
	deleted, err := r.RunTimeSweep(context.Background(), 5) // user-set 5 days
	if err != nil {
		t.Fatal(err)
	}
	if deleted != 0 {
		t.Errorf("deleted=%d, want 0 (cutoff floored to 30d tier window)", deleted)
	}
}
