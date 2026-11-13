package main

import (
	"context"
	"regexp"
	"testing"
)

// A stream for a host this process has no client for must fail, so the backend
// keeps retrying it instead of recording a stream that does not exist.
func TestStartStreamFailsForUnregisteredHost(t *testing.T) {
	sm := NewStreamManager(NewStatsCache())

	err := sm.StartStream(context.Background(), "abc123def456", "web", "unknown-host")

	if err == nil {
		t.Fatal("expected an error for a host with no Docker client")
	}
	if sm.GetStreamCount() != 0 {
		t.Fatalf("expected no stream to be recorded, got %d", sm.GetStreamCount())
	}
}

func TestInstanceIDIsRandomHex(t *testing.T) {
	a, err := newInstanceID()
	if err != nil {
		t.Fatal(err)
	}
	b, err := newInstanceID()
	if err != nil {
		t.Fatal(err)
	}

	if !regexp.MustCompile(`^[0-9a-f]{16}$`).MatchString(a) {
		t.Fatalf("instance id %q is not 16 hex chars", a)
	}
	if a == b {
		t.Fatal("two instance ids should differ")
	}
}
