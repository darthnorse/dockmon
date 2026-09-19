package client

import (
	"context"
	"io"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/darthnorse/dockmon-agent/internal/client/statsmsg"
	"github.com/darthnorse/dockmon-agent/internal/config"
	"github.com/darthnorse/dockmon-agent/internal/handlers"
	"github.com/sirupsen/logrus"
)

type fakeDualSendClient struct {
	mu     sync.Mutex
	runCtx context.Context
	runs   int
	builds int
}

func (f *fakeDualSendClient) Send(statsmsg.AgentStatsMsg) {}

func (f *fakeDualSendClient) Run(ctx context.Context) {
	f.mu.Lock()
	f.runCtx = ctx
	f.runs++
	f.mu.Unlock()
	<-ctx.Done()
}

func (f *fakeDualSendClient) buildCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.builds
}

func (f *fakeDualSendClient) runCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.runs
}

func (f *fakeDualSendClient) context() context.Context {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.runCtx
}

// handlerHasStatsService reports whether a handler's unexported statsService
// field is set, using the same strict-nil comparison the send paths use.
func handlerHasStatsService(t *testing.T, h interface{}) bool {
	t.Helper()
	f := reflect.ValueOf(h).Elem().FieldByName("statsService")
	if !f.IsValid() || f.Kind() != reflect.Interface {
		t.Fatalf("statsService field not found on %T", h)
	}
	return !f.IsNil()
}

func newDualSendTestClient(t *testing.T, token string) (*WebSocketClient, *fakeDualSendClient, func()) {
	t.Helper()
	log := logrus.New()
	log.SetOutput(io.Discard)

	ctx, cancel := context.WithCancel(context.Background())
	fake := &fakeDualSendClient{}

	c := &WebSocketClient{
		cfg: &config.Config{
			DockMonURL:     "https://dockmon.example",
			PermanentToken: token,
			DataPath:       t.TempDir(),
		},
		log:              log,
		procCtx:          ctx,
		statsHandler:     handlers.NewStatsHandler(nil, log, nil),
		hostStatsHandler: handlers.NewHostStatsHandler(log, nil, nil),
	}
	c.newStatsService = func(url, token string, insecure bool, log *logrus.Logger) statsServiceClient {
		fake.mu.Lock()
		fake.builds++
		fake.mu.Unlock()
		return fake
	}

	return c, fake, cancel
}

// The backend returns a permanent token on every reconnect, so a naive hook
// would start a second dual-send client per reconnect.
func TestEnsureStatsServiceDualSend_StartsExactlyOnce(t *testing.T) {
	c, fake, cancel := newDualSendTestClient(t, "perm-token")
	defer cancel()

	c.EnsureStatsServiceDualSend() // startup
	c.EnsureStatsServiceDualSend() // first registration
	c.EnsureStatsServiceDualSend() // reconnect

	if got := fake.buildCount(); got != 1 {
		t.Errorf("built %d dual-send clients, want 1", got)
	}
	waitForRuns(t, fake, 1)
	if got := fake.runCount(); got != 1 {
		t.Errorf("Run called %d times, want 1", got)
	}
}

// A1 is inert without this: HostStatsHandler has its own attach point, and
// wiring only StatsHandler would dual-send container samples alone.
func TestEnsureStatsServiceDualSend_AttachesBothHandlers(t *testing.T) {
	c, _, cancel := newDualSendTestClient(t, "perm-token")
	defer cancel()

	c.EnsureStatsServiceDualSend()

	if !handlerHasStatsService(t, c.statsHandler) {
		t.Error("container StatsHandler not attached to stats-service")
	}
	if !handlerHasStatsService(t, c.hostStatsHandler) {
		t.Error("HostStatsHandler not attached to stats-service; host metrics would never reach the evaluator")
	}
}

// The original defect: on an agent's first run the token is empty at startup
// and only arrives with the registration response.
func TestEnsureStatsServiceDualSend_StartsAfterTokenArrives(t *testing.T) {
	c, fake, cancel := newDualSendTestClient(t, "")
	defer cancel()

	c.EnsureStatsServiceDualSend() // startup: no token yet
	if got := fake.buildCount(); got != 0 {
		t.Fatalf("built %d clients without a token, want 0", got)
	}

	c.cfg.PermanentToken = "perm-token" // registration persisted it
	c.EnsureStatsServiceDualSend()

	if got := fake.buildCount(); got != 1 {
		t.Errorf("built %d clients after the token arrived, want 1", got)
	}
	waitForRuns(t, fake, 1)
	if !handlerHasStatsService(t, c.hostStatsHandler) {
		t.Error("HostStatsHandler not attached after post-registration start")
	}
}

func TestEnsureStatsServiceDualSend_NoStartWithoutURL(t *testing.T) {
	c, fake, cancel := newDualSendTestClient(t, "perm-token")
	defer cancel()
	c.cfg.DockMonURL = ""

	c.EnsureStatsServiceDualSend()

	if got := fake.buildCount(); got != 0 {
		t.Errorf("built %d clients without a URL, want 0", got)
	}
}

// The dual-send client must outlive any single WebSocket connection.
func TestEnsureStatsServiceDualSend_UsesProcessContext(t *testing.T) {
	c, fake, cancel := newDualSendTestClient(t, "perm-token")
	defer cancel()

	c.EnsureStatsServiceDualSend()
	waitForRuns(t, fake, 1)

	if fake.context() != c.procCtx {
		t.Error("dual-send client did not run on the process-lifetime context")
	}
	select {
	case <-fake.context().Done():
		t.Error("dual-send context already cancelled")
	default:
	}
}

func waitForRuns(t *testing.T, f *fakeDualSendClient, want int) {
	t.Helper()
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) {
		if f.runCount() >= want {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("Run called %d times, want %d", f.runCount(), want)
}
