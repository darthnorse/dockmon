package handlers_test

import (
	"testing"

	"github.com/darthnorse/dockmon-agent/internal/client"
	"github.com/darthnorse/dockmon-agent/internal/client/statsmsg"
	"github.com/darthnorse/dockmon-agent/internal/handlers"
	"github.com/sirupsen/logrus"
)

// TestStatsHandler_SetStatsServiceClient verifies the nil-safe setter. The
// full processStats→dual-send path is exercised by Task 25's end-to-end
// integration test.
//
// This test deliberately lives in package `handlers_test` (external test
// package) rather than `handlers`, because it needs to import
// `internal/client` to construct a real *StatsServiceClient, and
// `internal/client` imports `internal/handlers` — an in-package test would
// recreate the import cycle the rest of this file was structured to avoid.
func TestStatsHandler_SetStatsServiceClient(t *testing.T) {
	log := logrus.New()
	h := handlers.NewStatsHandler(nil, log, func(string, interface{}) error { return nil })

	// Default: disabled (nil). We cannot inspect the unexported field from
	// this package, so we exercise the setter through SendStatsForTest below
	// in subsequent tasks. For now, just confirm SetStatsServiceClient does
	// not panic with a real client, a typed nil, and an untyped nil.
	c := client.NewStatsServiceClient("http://localhost:0/never", "tok", log)
	h.SetStatsServiceClient(c)

	// Typed nil — common footgun: an interface holding a typed nil is not
	// == nil, but our setter normalizes this.
	var typedNil *client.StatsServiceClient
	h.SetStatsServiceClient(typedNil)

	// Untyped nil — should disable the dual-send.
	h.SetStatsServiceClient(nil)
}

// TestStatsServiceSender_InterfaceSatisfaction is a compile-time check that
// *client.StatsServiceClient satisfies handlers.StatsServiceSender. If this
// ever stops compiling, the contract between the two packages has drifted
// and main.go's wiring (Task 22) will break.
func TestStatsServiceSender_InterfaceSatisfaction(t *testing.T) {
	var _ handlers.StatsServiceSender = (*client.StatsServiceClient)(nil)
	// Also verify AgentStatsMsg round-trips through the alias.
	_ = statsmsg.AgentStatsMsg{ContainerID: "abc"}
	_ = client.AgentStatsMsg{ContainerID: "abc"}
}
