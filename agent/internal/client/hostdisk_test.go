package client

import (
	"context"
	"testing"
	"time"
)

// The data-root lookup is a daemon call made inside the host-stats tick. It
// must carry a deadline even when the caller's context has none, or a wedged
// daemon stalls host CPU/memory sampling.
func TestBoundedLookup_AddsDeadlineToUnboundedContext(t *testing.T) {
	var seen context.Context
	lookup := boundedLookup(func(ctx context.Context) (string, error) {
		seen = ctx
		return "/var/lib/docker", nil
	})

	root, err := lookup(context.Background())
	if err != nil || root != "/var/lib/docker" {
		t.Fatalf("root=%q err=%v", root, err)
	}
	deadline, ok := seen.Deadline()
	if !ok {
		t.Fatal("lookup context has no deadline")
	}
	if remaining := time.Until(deadline); remaining > dataRootLookupTimeout || remaining <= 0 {
		t.Errorf("deadline %v from now, want within %v", remaining, dataRootLookupTimeout)
	}
}

func TestBoundedLookup_ReturnsWhenTheDaemonNeverAnswers(t *testing.T) {
	lookup := boundedLookup(func(ctx context.Context) (string, error) {
		<-ctx.Done()
		return "", ctx.Err()
	})

	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	if _, err := lookup(ctx); err == nil {
		t.Fatal("expected a deadline error")
	}
}
