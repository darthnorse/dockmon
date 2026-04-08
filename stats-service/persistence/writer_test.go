package persistence

import (
	"context"
	"database/sql"
	"math"
	"testing"
	"time"
)

func makeWriterFixture(t *testing.T) (*DB, chan writeJob, *Writer) {
	t.Helper()
	path := makeFixtureDB(t)
	db, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Close() })
	if _, err := db.Write().Exec(
		`INSERT INTO docker_hosts (id, name) VALUES ('host-1','h1')`); err != nil {
		t.Fatal(err)
	}
	ch := make(chan writeJob, 4096)
	w := NewWriter(db, ch)
	return db, ch, w
}

func TestWriter_BatchPersistsContainerRows(t *testing.T) {
	db, ch, w := makeWriterFixture(t)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go w.Run(ctx)

	now := time.Unix(1_000_000, 0)
	ch <- writeJob{
		tier: "1h", isHost: false,
		entityID: "host-1:abc123abc123",
		ts:       now,
		value:    sample{CPU: 12.5, MemUsed: 1024, MemLimit: 8192, NetBps: 100.5},
	}

	time.Sleep(1500 * time.Millisecond)

	var count int
	if err := db.Read().QueryRow(
		`SELECT COUNT(*) FROM container_stats_history WHERE container_id = ?`,
		"host-1:abc123abc123",
	).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 1 {
		t.Errorf("got %d rows, want 1", count)
	}

	var cpu sql.NullFloat64
	if err := db.Read().QueryRow(
		`SELECT cpu_percent FROM container_stats_history WHERE container_id = ?`,
		"host-1:abc123abc123",
	).Scan(&cpu); err != nil {
		t.Fatal(err)
	}
	if !cpu.Valid || math.Abs(cpu.Float64-12.5) > 1e-6 {
		t.Errorf("cpu=%v, want 12.5", cpu)
	}
}

func TestWriter_BatchPersistsHostRows(t *testing.T) {
	db, ch, w := makeWriterFixture(t)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go w.Run(ctx)

	now := time.Unix(1_000_000, 0)
	ch <- writeJob{
		tier: "1h", isHost: true,
		entityID: "host-1",
		ts:       now,
		value: sample{
			CPU: 50, MemPercent: 60, MemUsed: 1 << 30, MemLimit: 4 << 30,
			NetBps: 1024, ContainerCount: 8,
		},
	}
	time.Sleep(1500 * time.Millisecond)

	var count int
	if err := db.Read().QueryRow(
		`SELECT COUNT(*) FROM host_stats_history WHERE host_id = 'host-1'`,
	).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 1 {
		t.Errorf("got %d rows, want 1", count)
	}
}

func TestWriter_NaNBecomesNull(t *testing.T) {
	db, ch, w := makeWriterFixture(t)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go w.Run(ctx)

	ch <- writeJob{
		tier: "1h", isHost: false,
		entityID: "host-1:nullsample00",
		ts:       time.Unix(1_000_000, 0),
		value:    sample{CPU: math.NaN(), NetBps: math.NaN()},
	}
	time.Sleep(1500 * time.Millisecond)

	var cpu sql.NullFloat64
	if err := db.Read().QueryRow(
		`SELECT cpu_percent FROM container_stats_history WHERE container_id = ?`,
		"host-1:nullsample00",
	).Scan(&cpu); err != nil {
		t.Fatal(err)
	}
	if cpu.Valid {
		t.Errorf("expected NULL cpu, got %v", cpu.Float64)
	}
}

func TestWriter_InsertOrReplaceDeduplicates(t *testing.T) {
	db, ch, w := makeWriterFixture(t)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go w.Run(ctx)

	ts := time.Unix(1_000_000, 0)
	ch <- writeJob{
		tier: "1h", entityID: "host-1:dup000000000", ts: ts,
		value: sample{CPU: 10},
	}
	ch <- writeJob{
		tier: "1h", entityID: "host-1:dup000000000", ts: ts,
		value: sample{CPU: 99},
	}
	time.Sleep(1500 * time.Millisecond)

	var cpu sql.NullFloat64
	if err := db.Read().QueryRow(
		`SELECT cpu_percent FROM container_stats_history WHERE container_id = ?`,
		"host-1:dup000000000",
	).Scan(&cpu); err != nil {
		t.Fatal(err)
	}
	if !cpu.Valid || cpu.Float64 != 99 {
		t.Errorf("cpu=%v, want 99 (replaced)", cpu)
	}
}

func TestWriter_FlushOnContextCancel(t *testing.T) {
	db, ch, w := makeWriterFixture(t)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		w.Run(ctx)
		close(done)
	}()

	ch <- writeJob{
		tier: "1h", entityID: "host-1:cancelflush", ts: time.Unix(1_000_000, 0),
		value: sample{CPU: 1},
	}
	time.Sleep(50 * time.Millisecond)
	cancel()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("writer Run did not return after cancel")
	}

	var count int
	if err := db.Read().QueryRow(
		`SELECT COUNT(*) FROM container_stats_history WHERE container_id = ?`,
		"host-1:cancelflush",
	).Scan(&count); err != nil {
		t.Fatal(err)
	}
	if count != 1 {
		t.Errorf("post-cancel rows=%d, want 1 (final flush)", count)
	}
}
