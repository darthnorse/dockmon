package handlers_test

import (
	"reflect"
	"testing"

	"github.com/darthnorse/dockmon-agent/internal/client"
	"github.com/darthnorse/dockmon-agent/internal/client/statsmsg"
	"github.com/darthnorse/dockmon-agent/internal/handlers"
	"github.com/sirupsen/logrus"
)

// statsServiceStrictlyNil peeks at the unexported StatsHandler.statsService
// field and reports whether it is strictly `== nil` — the same comparison
// processStats uses to decide whether to call .Send(). This intentionally
// does NOT unwrap typed-nil-in-interface: the whole point of the setter's
// normalization is to guarantee that if a typed-nil was passed in, the
// stored field is a strict-nil interface so `h.statsService != nil` in
// processStats is false. If we unwrapped, we'd paper over exactly the
// bug this test is meant to catch.
//
// Using reflection here is a deliberate test-only compromise: the full
// processStats dual-send path is exercised by the end-to-end integration test
// in stats-service, but verifying the normalization at this layer means the
// typed-nil footgun can't regress silently into a production panic.
func statsServiceStrictlyNil(t *testing.T, h *handlers.StatsHandler) bool {
	t.Helper()
	f := reflect.ValueOf(h).Elem().FieldByName("statsService")
	if !f.IsValid() {
		t.Fatalf("statsService field not found on StatsHandler")
	}
	if f.Kind() != reflect.Interface {
		t.Fatalf("statsService field is not an interface, got %s", f.Kind())
	}
	// reflect.Value.IsNil() on an interface kind is true ONLY when the
	// interface itself is the strict-nil `(nil, nil)` pair — exactly the
	// `== nil` semantics the production code relies on. A typed-nil-in-
	// interface returns false here, which is the failure the setter must
	// prevent.
	return f.IsNil()
}

// TestStatsHandler_SetStatsServiceClient verifies the nil-safe setter.
//
// This test deliberately lives in package `handlers_test` (external test
// package) rather than `handlers`, because it needs to import
// `internal/client` to construct a real *StatsServiceClient, and
// `internal/client` imports `internal/handlers` — an in-package test would
// recreate the import cycle the rest of this file was structured to avoid.
func TestStatsHandler_SetStatsServiceClient(t *testing.T) {
	log := logrus.New()
	h := handlers.NewStatsHandler(nil, log, func(string, interface{}) error { return nil })

	// Default: disabled — statsService must be strictly nil before the setter is called.
	if !statsServiceStrictlyNil(t, h) {
		t.Fatalf("statsService should default to strictly nil")
	}

	// Real client enables the dual-send.
	c := client.NewStatsServiceClient("http://localhost:0/never", "tok", log)
	h.SetStatsServiceClient(c)
	if statsServiceStrictlyNil(t, h) {
		t.Fatalf("statsService should be non-nil after setting a real client")
	}

	// Typed nil — the common footgun. An interface holding a typed nil is
	// not == untyped nil, so the setter MUST normalize the stored field
	// back to strict nil or processStats will take the non-nil branch and
	// panic on a nil receiver in .Send().
	var typedNil *client.StatsServiceClient
	h.SetStatsServiceClient(typedNil)
	if !statsServiceStrictlyNil(t, h) {
		t.Fatalf("statsService should be strictly nil after SetStatsServiceClient(typedNil) — typed-nil-in-interface normalization failed")
	}

	// Set to non-nil, then clear via untyped nil.
	h.SetStatsServiceClient(c)
	h.SetStatsServiceClient(nil)
	if !statsServiceStrictlyNil(t, h) {
		t.Fatalf("statsService should be strictly nil after SetStatsServiceClient(nil)")
	}
}

// TestStatsServiceSender_InterfaceSatisfaction is a compile-time check that
// *client.StatsServiceClient satisfies handlers.StatsServiceSender.
func TestStatsServiceSender_InterfaceSatisfaction(t *testing.T) {
	var _ handlers.StatsServiceSender = (*client.StatsServiceClient)(nil)
	// Also verify AgentStatsMsg round-trips through the alias.
	_ = statsmsg.AgentStatsMsg{ContainerID: "abc"}
	_ = client.AgentStatsMsg{ContainerID: "abc"}
}
