package handlers_test

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/handlers"
	"github.com/sirupsen/logrus"
)

// silentLogger returns a logrus logger that discards output so tests stay quiet.
func silentLogger() *logrus.Logger {
	l := logrus.New()
	l.SetOutput(io.Discard)
	return l
}

// drainUntilQuiet empties ch until no value arrives for the settle window. Used
// to discard any results (including late, context-cancelled in-flight checks)
// produced by a previous connection before observing the next one.
func drainUntilQuiet(ch <-chan string, settle time.Duration) {
	for {
		select {
		case <-ch:
		case <-time.After(settle):
			return
		}
	}
}

// TestHealthCheckHandler_ResumesAfterReconnect verifies the health-check loop
// still runs checks after a Stop()/Start() cycle — i.e. after the agent's
// WebSocket drops and reconnects in-process.
//
// Regression: the handler is created once and reused across reconnects, but its
// stop signal was a one-shot channel closed on the first Stop() and never
// recreated. Every reconnect's loop then exited immediately, silently disabling
// all container health checks until a full process restart.
func TestHealthCheckHandler_ResumesAfterReconnect(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	results := make(chan string, 16)
	sendEvent := func(msgType string, _ interface{}) error {
		if msgType == "health_check_result" {
			select {
			case results <- msgType:
			default:
			}
		}
		return nil
	}

	h := handlers.NewHealthCheckHandler(silentLogger(), sendEvent)
	h.UpdateConfig(&handlers.HealthCheckConfig{
		ContainerID:          "test-container",
		Enabled:              true,
		URL:                  server.URL,
		Method:               "GET",
		ExpectedStatusCodes:  "200",
		TimeoutSeconds:       5,
		CheckIntervalSeconds: 1,
	})

	waitForCheck := func(phase string) {
		t.Helper()
		select {
		case <-results:
		case <-time.After(4 * time.Second):
			t.Fatalf("no health check ran during %s", phase)
		}
	}

	// First connection: the loop should run checks. This also proves the test
	// harness (server, config, event callback) works.
	ctx1, cancel1 := context.WithCancel(context.Background())
	h.Start(ctx1)
	waitForCheck("first connection")

	// Disconnect: mirror websocket.go teardown — cancel the connection context,
	// then Stop() the handler.
	cancel1()
	h.Stop()

	// Discard anything the first connection left behind so the next assertion can
	// only succeed on a check produced by the reconnected loop.
	drainUntilQuiet(results, 300*time.Millisecond)

	// Reconnect: the loop must run checks again.
	ctx2, cancel2 := context.WithCancel(context.Background())
	h.Start(ctx2)
	defer func() {
		cancel2()
		h.Stop()
	}()
	waitForCheck("after reconnect")
}

// TestHealthCheckHandler_StopAfterDoubleStartDoesNotHang verifies that a second
// Start() without an intervening Stop() does not strand the first loop. Without
// defensive handling, the first Start()'s CancelFunc is overwritten and its loop
// never cancelled, so Stop()'s wg.Wait() blocks forever on the orphaned loop.
func TestHealthCheckHandler_StopAfterDoubleStartDoesNotHang(t *testing.T) {
	h := handlers.NewHealthCheckHandler(silentLogger(), func(string, interface{}) error { return nil })

	ctx1, cancel1 := context.WithCancel(context.Background())
	defer cancel1()
	ctx2, cancel2 := context.WithCancel(context.Background())
	defer cancel2()

	h.Start(ctx1)
	h.Start(ctx2) // second Start with no intervening Stop

	done := make(chan struct{})
	go func() {
		h.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("Stop() hung after a second Start() without an intervening Stop()")
	}
}

// TestHealthCheckHandler_NoResultEmittedAfterStop verifies that a health check
// in flight when Stop() is called does not emit a (stale) result afterward —
// which would otherwise land on the next reconnected WebSocket. The check is
// held open until its request context is cancelled by Stop().
func TestHealthCheckHandler_NoResultEmittedAfterStop(t *testing.T) {
	reqStarted := make(chan struct{}, 1)
	server := httptest.NewServer(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
		select {
		case reqStarted <- struct{}{}:
		default:
		}
		<-r.Context().Done() // block until the client (Stop) cancels the request
	}))
	defer server.Close()

	results := make(chan string, 16)
	sendEvent := func(msgType string, _ interface{}) error {
		if msgType == "health_check_result" {
			results <- msgType
		}
		return nil
	}

	h := handlers.NewHealthCheckHandler(silentLogger(), sendEvent)
	h.UpdateConfig(&handlers.HealthCheckConfig{
		ContainerID:          "test-container",
		Enabled:              true,
		URL:                  server.URL,
		Method:               "GET",
		ExpectedStatusCodes:  "200",
		TimeoutSeconds:       30,
		CheckIntervalSeconds: 1,
	})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	h.Start(ctx)

	// Wait until a check is actually in flight (the server received the request).
	select {
	case <-reqStarted:
	case <-time.After(4 * time.Second):
		t.Fatal("health check never started")
	}

	// Stop while the check is in flight. It must not emit a result.
	h.Stop()

	select {
	case <-results:
		t.Fatal("health check result emitted after Stop()")
	case <-time.After(300 * time.Millisecond):
		// good: nothing emitted
	}
}
