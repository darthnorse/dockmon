package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	cerrdefs "github.com/containerd/errdefs"
	"github.com/darthnorse/dockmon-agent/internal/docker"
	"github.com/docker/docker/api/types/container"
	"github.com/sirupsen/logrus"
	logrustest "github.com/sirupsen/logrus/hooks/test"
)

// --- test doubles -----------------------------------------------------------

// scriptedBody is a stats stream body driven by the test: frames are handed
// over one at a time, and a nil/never-fed channel models a stream that stays
// open but silent (the case the idle watchdog exists for).
type scriptedBody struct {
	ctx     context.Context
	frames  chan []byte
	endErr  error
	onRead  func()
	mu      sync.Mutex
	buf     []byte
	closed  bool
	ignores bool // when true, Read ignores ctx — models a wedged body
}

func (b *scriptedBody) Read(p []byte) (int, error) {
	if b.onRead != nil {
		b.onRead()
	}
	for len(b.buf) == 0 {
		if b.ignores {
			f, ok := <-b.frames
			if !ok {
				return 0, b.endErr
			}
			b.buf = f
			continue
		}
		select {
		case <-b.ctx.Done():
			return 0, b.ctx.Err()
		case f, ok := <-b.frames:
			if !ok {
				return 0, b.endErr
			}
			b.buf = f
		}
	}
	n := copy(p, b.buf)
	b.buf = b.buf[n:]
	return n, nil
}

func (b *scriptedBody) Close() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.closed = true
	return nil
}

func (b *scriptedBody) isClosed() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.closed
}

// statsAttempt scripts one ContainerStats call.
type statsAttempt struct {
	err     error
	frames  [][]byte    // delivered in order, then endErr
	feed    chan []byte // when set, used instead of frames; closing it ends the stream
	endErr  error
	silent  bool  // never deliver anything, never close
	wedged  bool  // body ignores context cancellation
	hangs   bool  // the open itself never answers until the context ends
	hangErr error // when hangs is set, the error the open finally returns
	onRead  func()
	body    *scriptedBody
	started chan struct{}
}

type fakeStatsClient struct {
	mu     sync.Mutex
	script []*statsAttempt // consumed in order; the last entry repeats
	calls  int
	listFn func(ctx context.Context) ([]docker.ContainerWithDigest, error)
}

func (f *fakeStatsClient) ListContainers(ctx context.Context) ([]docker.ContainerWithDigest, error) {
	if f.listFn != nil {
		return f.listFn(ctx)
	}
	return nil, nil
}

func (f *fakeStatsClient) ContainerStats(ctx context.Context, containerID string, stream bool) (container.StatsResponseReader, error) {
	f.mu.Lock()
	idx := f.calls
	f.calls++
	if idx >= len(f.script) {
		idx = len(f.script) - 1
	}
	att := f.script[idx]
	f.mu.Unlock()

	if att.started != nil {
		select {
		case att.started <- struct{}{}:
		default:
		}
	}
	if att.hangs {
		<-ctx.Done()
		if att.hangErr != nil {
			return container.StatsResponseReader{}, att.hangErr
		}
		return container.StatsResponseReader{}, ctx.Err()
	}
	if att.err != nil {
		return container.StatsResponseReader{}, att.err
	}

	frames := att.feed
	if frames == nil {
		frames = make(chan []byte, len(att.frames))
		for _, fr := range att.frames {
			frames <- fr
		}
		if !att.silent {
			close(frames)
		}
	}
	end := att.endErr
	if end == nil {
		end = io.EOF
	}
	body := &scriptedBody{ctx: ctx, frames: frames, endErr: end, onRead: att.onRead, ignores: att.wedged}

	f.mu.Lock()
	att.body = body
	f.mu.Unlock()

	return container.StatsResponseReader{Body: body, OSType: "linux"}, nil
}

func (f *fakeStatsClient) attemptCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.calls
}

func (f *fakeStatsClient) bodyAt(i int) *scriptedBody {
	f.mu.Lock()
	defer f.mu.Unlock()
	if i >= len(f.script) {
		return nil
	}
	return f.script[i].body
}

// fakeClock drives the duration-based decisions (stable attempt, warn
// throttle) without sleeping.
type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func newFakeClock() *fakeClock {
	return &fakeClock{t: time.Date(2026, 8, 5, 12, 0, 0, 0, time.UTC)}
}

func (c *fakeClock) Now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t = c.t.Add(d)
}

// waitRecorder replaces the retry sleep: it records the backoff the collector
// asked for and returns instantly.
type waitRecorder struct {
	mu     sync.Mutex
	waits  []time.Duration
	stopAt int // return false (cancelled) on this call number; 0 = never
	onWait func(n int)
}

func (w *waitRecorder) wait(ctx context.Context, d time.Duration) bool {
	w.mu.Lock()
	w.waits = append(w.waits, d)
	n := len(w.waits)
	w.mu.Unlock()

	if w.onWait != nil {
		w.onWait(n)
	}
	if ctx.Err() != nil {
		return false
	}
	return w.stopAt == 0 || n < w.stopAt
}

func (w *waitRecorder) recorded() []time.Duration {
	w.mu.Lock()
	defer w.mu.Unlock()
	out := make([]time.Duration, len(w.waits))
	copy(out, w.waits)
	return out
}

type sentMessage struct {
	msgType string
	payload map[string]interface{}
}

type messageRecorder struct {
	mu     sync.Mutex
	sent   []sentMessage
	onSend func()
}

func (m *messageRecorder) send(msgType string, payload interface{}) error {
	m.mu.Lock()
	p, _ := payload.(map[string]interface{})
	m.sent = append(m.sent, sentMessage{msgType: msgType, payload: p})
	m.mu.Unlock()
	if m.onSend != nil {
		m.onSend()
	}
	return nil
}

func (m *messageRecorder) count() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.sent)
}

// --- frame helpers ----------------------------------------------------------

func liveFrame(t *testing.T, cpuTotal uint64) []byte {
	t.Helper()
	s := container.StatsResponse{
		Read: time.Date(2026, 8, 5, 12, 0, 0, 0, time.UTC),
		ID:   "abcdef123456",
		Name: "/probe",
	}
	s.CPUStats.CPUUsage.TotalUsage = cpuTotal
	s.CPUStats.SystemUsage = cpuTotal * 10
	s.CPUStats.OnlineCPUs = 2
	s.MemoryStats.Usage = 1024 * 1024
	s.MemoryStats.Limit = 8 * 1024 * 1024
	b, err := json.Marshal(s)
	if err != nil {
		t.Fatalf("marshal live frame: %v", err)
	}
	return b
}

// zeroFrame is what the daemon actually publishes for a container that is not
// running: the stream stays open and every frame carries a zero read time.
func zeroFrame(t *testing.T) []byte {
	t.Helper()
	b, err := json.Marshal(container.StatsResponse{ID: "abcdef123456", Name: "/probe"})
	if err != nil {
		t.Fatalf("marshal zero frame: %v", err)
	}
	return b
}

// --- harness ----------------------------------------------------------------

type retryHarness struct {
	h      *StatsHandler
	client *fakeStatsClient
	waits  *waitRecorder
	msgs   *messageRecorder
	sink   *fakeStatsSender
	clock  *fakeClock
	hook   *logrustest.Hook
}

func newRetryHarness(t *testing.T, script ...*statsAttempt) *retryHarness {
	t.Helper()
	log, hook := logrustest.NewNullLogger()
	log.SetLevel(logrus.DebugLevel)

	client := &fakeStatsClient{script: script}
	waits := &waitRecorder{}
	msgs := &messageRecorder{}
	sink := &fakeStatsSender{}
	clock := newFakeClock()

	h := newStatsHandler(client, log, msgs.send)
	h.wait = waits.wait
	h.now = clock.Now
	h.idleTimeout = 50 * time.Millisecond
	h.SetStatsServiceClient(sink)

	return &retryHarness{h: h, client: client, waits: waits, msgs: msgs, sink: sink, clock: clock, hook: hook}
}

func waitFor(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

func (r *retryHarness) streamCount() int {
	r.h.streamsMu.RLock()
	defer r.h.streamsMu.RUnlock()
	return len(r.h.streams)
}

// --- retry ------------------------------------------------------------------

// TestCollector_RetriesAfterOpenError is the headline regression: today the
// goroutine returns for good when ContainerStats fails.
func TestCollector_RetriesAfterOpenError(t *testing.T) {
	r := newRetryHarness(t,
		&statsAttempt{err: fmt.Errorf("connection refused")},
		&statsAttempt{frames: [][]byte{liveFrame(t, 100)}},
	)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}

	waitFor(t, "a sample after the failed attempt", func() bool { return r.msgs.count() > 0 })
	if got := r.client.attemptCount(); got < 2 {
		t.Fatalf("expected the collector to reopen the stream, got %d attempt(s)", got)
	}
}

// TestCollector_RetriesAfterDecodeError covers the mid-stream failure.
func TestCollector_RetriesAfterDecodeError(t *testing.T) {
	r := newRetryHarness(t,
		&statsAttempt{frames: [][]byte{liveFrame(t, 100), []byte("{not json")}},
		&statsAttempt{frames: [][]byte{liveFrame(t, 200)}},
	)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}

	waitFor(t, "a sample from the reopened stream", func() bool { return r.msgs.count() >= 2 })
	if got := r.client.attemptCount(); got < 2 {
		t.Fatalf("expected a second attempt after the decode error, got %d", got)
	}
}

// TestCollector_BackoffSequence pins the capped exponential schedule.
func TestCollector_BackoffSequence(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{err: fmt.Errorf("boom")})
	r.waits.stopAt = 8

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to give up on cancellation", func() bool { return r.streamCount() == 0 })

	want := []time.Duration{
		1 * time.Second, 2 * time.Second, 4 * time.Second, 8 * time.Second,
		16 * time.Second, 30 * time.Second, 30 * time.Second, 30 * time.Second,
	}
	got := r.waits.recorded()
	if len(got) != len(want) {
		t.Fatalf("waits = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("wait[%d] = %v, want %v (full: %v)", i, got[i], want[i], got)
		}
	}
}

// TestCollector_BackoffResetsOnlyAfterStableStream: a stream that yields one
// frame and dies must not reset the backoff, or it retries every second
// forever.
func TestCollector_BackoffResetsOnlyAfterStableStream(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{frames: [][]byte{liveFrame(t, 100)}})
	r.waits.stopAt = 4

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	want := []time.Duration{1 * time.Second, 2 * time.Second, 4 * time.Second, 8 * time.Second}
	got := r.waits.recorded()
	for i := range want {
		if i >= len(got) || got[i] != want[i] {
			t.Fatalf("short-lived streams must keep escalating: got %v, want prefix %v", got, want)
		}
	}
}

// TestCollector_BackoffResetsAfterStableStream is the positive case: an
// attempt that carried a live frame for longer than the stable threshold
// starts the next backoff from scratch.
func TestCollector_BackoffResetsAfterStableStream(t *testing.T) {
	r := newRetryHarness(t,
		&statsAttempt{err: fmt.Errorf("boom")},
		&statsAttempt{err: fmt.Errorf("boom")},
		&statsAttempt{frames: [][]byte{liveFrame(t, 100), liveFrame(t, 200)}},
		&statsAttempt{err: fmt.Errorf("boom")},
	)
	r.waits.stopAt = 4
	// The clock only moves while a live stream is running, so attempt 3 looks
	// long-lived and every other attempt looks instantaneous.
	r.msgs.onSend = func() { r.clock.advance(45 * time.Second) }

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	// Without the reset the third and fourth waits would be 4s and 8s.
	got := r.waits.recorded()
	want := []time.Duration{1 * time.Second, 2 * time.Second, 1 * time.Second, 2 * time.Second}
	if len(got) != len(want) {
		t.Fatalf("waits = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("wait[%d] = %v, want %v (full: %v)", i, got[i], want[i], got)
		}
	}
}

// TestCollector_ClosesBodyPerAttempt guards against leaking an HTTP body per
// retry.
func TestCollector_ClosesBodyPerAttempt(t *testing.T) {
	r := newRetryHarness(t,
		&statsAttempt{frames: [][]byte{liveFrame(t, 100)}},
		&statsAttempt{frames: [][]byte{liveFrame(t, 200)}},
	)
	r.waits.stopAt = 2

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	for i := 0; i < 2; i++ {
		b := r.client.bodyAt(i)
		if b == nil {
			t.Fatalf("attempt %d never opened a body", i)
		}
		if !b.isClosed() {
			t.Fatalf("attempt %d body was not closed", i)
		}
	}
}

// TestCollector_StopsWhenContainerRemoved: a removed container answers 404 on
// the stats open, which is the one non-cancellation reason to stop for good.
func TestCollector_StopsWhenContainerRemoved(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{
		// Wrapped on purpose: IsNotFound must survive an error chain. The
		// unwrapped shape the Docker SDK actually returns is covered below.
		err: fmt.Errorf("failed to open stats stream: %w", cerrdefs.ErrNotFound),
	})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	if got := r.client.attemptCount(); got != 1 {
		t.Fatalf("a removed container must not be retried, got %d attempts", got)
	}
	if got := len(r.waits.recorded()); got != 0 {
		t.Fatalf("a removed container must not back off, got %d waits", got)
	}
}

// --- stopped containers -----------------------------------------------------

// TestCollector_SuppressesZeroReadFrames covers the live defect: the daemon
// keeps publishing zeroed frames for a stopped container, and those were
// reaching both the backend and the alert wire as a healthy idle host.
func TestCollector_SuppressesZeroReadFrames(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{frames: [][]byte{zeroFrame(t), zeroFrame(t)}})
	r.waits.stopAt = 1

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	if got := r.msgs.count(); got != 0 {
		t.Fatalf("zero-read frames must not be sent to the backend, got %d message(s)", got)
	}
	if got := len(r.sink.messages()); got != 0 {
		t.Fatalf("zero-read frames must not be dual-sent to stats-service, got %d", got)
	}
}

// TestCollector_ReattachesWhenContainerRunsAgain is the decisive lifecycle
// test: no start event ever arrives (the event stream can die permanently),
// the container is stopped for a while, and the collector must pick it up by
// itself once it runs again.
func TestCollector_ReattachesWhenContainerRunsAgain(t *testing.T) {
	r := newRetryHarness(t,
		&statsAttempt{frames: [][]byte{zeroFrame(t)}},
		&statsAttempt{frames: [][]byte{zeroFrame(t)}},
		&statsAttempt{frames: [][]byte{liveFrame(t, 100)}},
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}

	waitFor(t, "the collector to reattach on its own", func() bool { return r.msgs.count() > 0 })
	r.h.StopContainerStats("abcdef123456")
}

// --- lifecycle races --------------------------------------------------------

// TestReleaseStream_OnlyDeletesOwnEntry: a departing collector must not remove
// a newer collector's cancel func, which would orphan it and allow a duplicate.
func TestReleaseStream_OnlyDeletesOwnEntry(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{err: fmt.Errorf("unused")})

	old := &statsStream{cancel: func() {}}
	current := &statsStream{cancel: func() {}}

	r.h.streamsMu.Lock()
	r.h.streams["abcdef123456"] = current
	r.h.streamsMu.Unlock()

	r.h.releaseStream("abcdef123456", old)

	r.h.streamsMu.RLock()
	got := r.h.streams["abcdef123456"]
	r.h.streamsMu.RUnlock()
	if got != current {
		t.Fatalf("release by a stale collector deleted the live entry")
	}

	r.h.releaseStream("abcdef123456", current)
	if r.streamCount() != 0 {
		t.Fatalf("a collector must release its own entry")
	}
}

// TestCollector_StopsDuringBackoffWait: cancelling while the collector is
// waiting must end it promptly and deregister it.
func TestCollector_StopsDuringBackoffWait(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{err: fmt.Errorf("boom")})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	r.waits.onWait = func(n int) {
		if n == 1 {
			r.h.StopContainerStats("abcdef123456")
		}
	}

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	attempts := r.client.attemptCount()
	time.Sleep(50 * time.Millisecond)
	if got := r.client.attemptCount(); got != attempts {
		t.Fatalf("collector kept running after cancellation: %d -> %d attempts", attempts, got)
	}
}

// TestCollector_DropsFrameDecodedDuringCancellation: the frame is already
// decoded when cancellation lands, and must not be sent on a socket the next
// connection owns.
func TestCollector_DropsFrameDecodedDuringCancellation(t *testing.T) {
	var once sync.Once
	att := &statsAttempt{frames: [][]byte{liveFrame(t, 100)}}
	r := newRetryHarness(t, att)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	att.onRead = func() {
		once.Do(func() { r.h.StopContainerStats("abcdef123456") })
	}

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	if got := r.msgs.count(); got != 0 {
		t.Fatalf("a frame decoded during cancellation must not be sent, got %d", got)
	}
}

// TestStartContainerStats_RejectsCancelledParent: a start arriving during
// teardown must not leave an entry bound to a dead context — the next
// connection would see it and skip the container.
func TestStartContainerStats_RejectsCancelledParent(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{frames: [][]byte{liveFrame(t, 100)}})

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	if r.streamCount() != 0 {
		t.Fatalf("a start with a cancelled parent context must not register a stream")
	}
	time.Sleep(20 * time.Millisecond)
	if got := r.client.attemptCount(); got != 0 {
		t.Fatalf("a start with a cancelled parent context must not open a stream, got %d", got)
	}
}

// TestStopAll_AllowsRestartWhileOldCollectorDrains: the previous connection's
// collector can still be winding down (wedged body) when the next connection
// starts; it must not block the new collector or delete its entry.
func TestStopAll_AllowsRestartWhileOldCollectorDrains(t *testing.T) {
	drain := make(chan []byte)
	r := newRetryHarness(t,
		&statsAttempt{wedged: true, feed: drain, started: make(chan struct{}, 1)},
		&statsAttempt{frames: [][]byte{liveFrame(t, 100)}},
	)
	defer close(drain)

	conn1, cancel1 := context.WithCancel(context.Background())
	if err := r.h.StartContainerStats(conn1, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the first collector to open its stream", func() bool { return r.client.attemptCount() >= 1 })

	r.h.StopAll()
	cancel1()

	conn2, cancel2 := context.WithCancel(context.Background())
	defer cancel2()
	if err := r.h.StartContainerStats(conn2, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats (second connection): %v", err)
	}

	waitFor(t, "the new collector to deliver a sample", func() bool { return r.msgs.count() > 0 })
	if r.streamCount() != 1 {
		t.Fatalf("the new connection's entry must survive the old collector's release")
	}
}

// --- watchdog and logging ---------------------------------------------------

// TestCollector_AbandonsIdleStream: a stream that stays open but silent would
// otherwise block in Decode forever.
func TestCollector_AbandonsIdleStream(t *testing.T) {
	r := newRetryHarness(t,
		&statsAttempt{silent: true},
		&statsAttempt{frames: [][]byte{liveFrame(t, 100)}},
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}

	waitFor(t, "the idle stream to be abandoned and retried", func() bool { return r.msgs.count() > 0 })
	if b := r.client.bodyAt(0); b == nil || !b.isClosed() {
		t.Fatalf("the abandoned attempt's body must be closed")
	}
}

// TestCollector_AbandonsWedgedOpen: the Docker client has no request timeout,
// so an open that never answers would block the collector for the life of the
// connection unless the watchdog is armed before the call.
func TestCollector_AbandonsWedgedOpen(t *testing.T) {
	r := newRetryHarness(t,
		&statsAttempt{hangs: true},
		&statsAttempt{frames: [][]byte{liveFrame(t, 100)}},
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}

	waitFor(t, "the hung open to be abandoned and retried", func() bool { return r.msgs.count() > 0 })

	for _, e := range r.hook.AllEntries() {
		if e.Level == logrus.WarnLevel && strings.Contains(e.Message, errStreamIdle.Error()) {
			return
		}
	}
	t.Fatalf("a watchdog abort must be named in the log, not reported as a bare cancellation")
}

// TestCollector_StableRequiresLiveSampleDuration: an attempt whose first frame
// arrives late is not evidence of a healthy stream, so it must not reset the
// backoff.
func TestCollector_StableRequiresLiveSampleDuration(t *testing.T) {
	att := &statsAttempt{frames: [][]byte{liveFrame(t, 100)}}
	// The failing attempt first, so a wrongly-granted reset is visible as a
	// backoff that drops back to 1s instead of doubling.
	r := newRetryHarness(t, &statsAttempt{err: fmt.Errorf("boom")}, att)
	r.waits.stopAt = 2

	// The stream then takes 45s to produce its first frame, and dies.
	var once sync.Once
	att.onRead = func() { once.Do(func() { r.clock.advance(45 * time.Second) }) }

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	// Measured from the open, a 45s wait for the first frame would look stable
	// and reset the backoff to 1s.
	got := r.waits.recorded()
	want := []time.Duration{1 * time.Second, 2 * time.Second}
	if len(got) != len(want) || got[1] != want[1] {
		t.Fatalf("a slow first frame must not count as a stable stream: waits = %v, want %v", got, want)
	}
}

// TestCollector_OneFrameStreamsDoNotBypassWarnThrottle: recovery used to reset
// the throttle on the first live frame, so a stream that served one frame per
// retry logged a warning and a recovery every cycle.
func TestCollector_OneFrameStreamsDoNotBypassWarnThrottle(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{frames: [][]byte{liveFrame(t, 100)}})
	r.waits.stopAt = 5

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	warns, recoveries := 0, 0
	for _, e := range r.hook.AllEntries() {
		switch {
		case e.Level == logrus.WarnLevel:
			warns++
		case e.Level == logrus.InfoLevel && strings.Contains(e.Message, "recovered"):
			recoveries++
		}
	}
	if warns != 1 {
		t.Fatalf("expected 1 warning across 5 short-lived attempts, got %d", warns)
	}
	if recoveries != 0 {
		t.Fatalf("a one-frame stream must not log recovery, got %d", recoveries)
	}
}

// TestCollector_IdleWindowExcludesSendLatency: the watchdog measures daemon
// silence, so a slow send must not eat the window. Timing-based by nature; the
// margins are wide.
func TestCollector_IdleWindowExcludesSendLatency(t *testing.T) {
	frames := make(chan []byte, 2)
	frames <- liveFrame(t, 100)

	r := newRetryHarness(t, &statsAttempt{feed: frames})
	r.h.idleTimeout = 400 * time.Millisecond
	r.msgs.onSend = func() { time.Sleep(300 * time.Millisecond) }

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the first sample", func() bool { return r.msgs.count() == 1 })

	// 500ms after the first frame: past the window if it were still measured
	// from the decode (400ms), inside it when measured from the end of the
	// 300ms send (700ms).
	time.Sleep(500 * time.Millisecond)
	frames <- liveFrame(t, 200)

	waitFor(t, "the second sample on the same attempt", func() bool { return r.msgs.count() == 2 })
	if got := r.client.attemptCount(); got != 1 {
		t.Fatalf("the stream was reopened %d times; a slow send must not trip the watchdog", got)
	}
	close(frames)
}

// TestCollector_SingleFrameIsNeverStable: one frame followed by a long silence
// is not a healthy stream, however much time passes before the attempt ends.
func TestCollector_SingleFrameIsNeverStable(t *testing.T) {
	r := newRetryHarness(t,
		&statsAttempt{err: fmt.Errorf("boom")},
		&statsAttempt{frames: [][]byte{liveFrame(t, 100)}},
	)
	r.waits.stopAt = 2
	// Time passes while that single frame is being sent.
	r.msgs.onSend = func() { r.clock.advance(45 * time.Second) }

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	got := r.waits.recorded()
	if len(got) < 2 || got[1] != 2*time.Second {
		t.Fatalf("a single frame must not reset the backoff: waits = %v, want second wait 2s", got)
	}
	for _, e := range r.hook.AllEntries() {
		if e.Level == logrus.InfoLevel && strings.Contains(e.Message, "recovered") {
			t.Fatalf("a single frame must not claim recovery")
		}
	}
}

// TestCollector_SendLongerThanIdleTimeoutDoesNotTripWatchdog: the watchdog is
// disarmed across the send, so backpressure on the shared WebSocket write lock
// cannot be mistaken for a wedged daemon.
func TestCollector_SendLongerThanIdleTimeoutDoesNotTripWatchdog(t *testing.T) {
	frames := make(chan []byte, 2)
	frames <- liveFrame(t, 100)

	r := newRetryHarness(t, &statsAttempt{feed: frames})
	r.h.idleTimeout = 200 * time.Millisecond

	var once sync.Once
	r.msgs.onSend = func() { once.Do(func() { time.Sleep(400 * time.Millisecond) }) }

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the first sample", func() bool { return r.msgs.count() == 1 })

	frames <- liveFrame(t, 200)
	waitFor(t, "the second sample on the same attempt", func() bool { return r.msgs.count() == 2 })

	if got := r.client.attemptCount(); got != 1 {
		t.Fatalf("a send longer than idleTimeout reopened the stream %d times", got)
	}
	close(frames)
}

// TestCollector_WatchdogDoesNotMaskNotFound: if removal races the watchdog, the
// terminal 404 must survive error classification or the collector retries a
// container that no longer exists, forever.
func TestCollector_WatchdogDoesNotMaskNotFound(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{hangs: true, hangErr: cerrdefs.ErrNotFound})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	if got := r.client.attemptCount(); got != 1 {
		t.Fatalf("a removed container must not be retried, got %d attempts", got)
	}
}

// TestCollector_ThrottlesFailureWarnings keeps a wedged daemon from flooding
// the log while still resurfacing a persistent fault.
func TestCollector_ThrottlesFailureWarnings(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{err: fmt.Errorf("boom")})
	r.h.warnInterval = 5 * time.Minute
	r.waits.stopAt = 4
	r.waits.onWait = func(n int) {
		if n == 3 {
			r.clock.advance(6 * time.Minute)
		}
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	warns := 0
	for _, e := range r.hook.AllEntries() {
		if e.Level == logrus.WarnLevel {
			warns++
		}
	}
	if warns != 2 {
		t.Fatalf("expected 2 warnings (first failure + one after the interval), got %d", warns)
	}
}

// TestCollector_LogsRecoveryOnce: a healthy stream never returns to the outer
// loop, so recovery has to be reported from inside the decode loop.
func TestCollector_LogsRecoveryOnce(t *testing.T) {
	r := newRetryHarness(t,
		&statsAttempt{err: fmt.Errorf("boom")},
		&statsAttempt{frames: [][]byte{liveFrame(t, 100), liveFrame(t, 200), liveFrame(t, 300)}},
	)
	r.waits.stopAt = 2
	// Recovery is only claimed once the stream has been live long enough.
	r.msgs.onSend = func() { r.clock.advance(45 * time.Second) }

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	infos := 0
	for _, e := range r.hook.AllEntries() {
		if e.Level == logrus.InfoLevel && strings.Contains(e.Message, "recovered") {
			infos++
		}
	}
	if infos != 1 {
		t.Fatalf("expected exactly one recovery log, got %d", infos)
	}
}

// TestCollector_StopsOnUnwrappedNotFound covers the shape the Docker SDK
// actually returns: internal/docker.Client.ContainerStats passes its error
// through without wrapping.
func TestCollector_StopsOnUnwrappedNotFound(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{err: cerrdefs.ErrNotFound})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartContainerStats(ctx, "abcdef123456", "probe"); err != nil {
		t.Fatalf("StartContainerStats: %v", err)
	}
	waitFor(t, "the collector to stop", func() bool { return r.streamCount() == 0 })

	if got := r.client.attemptCount(); got != 1 {
		t.Fatalf("a removed container must not be retried, got %d attempts", got)
	}
}

// --- startup ----------------------------------------------------------------

// TestStartStatsCollection_HandlesContainerWithoutNames guards the unchecked
// Names[0] index.
func TestStartStatsCollection_HandlesContainerWithoutNames(t *testing.T) {
	r := newRetryHarness(t, &statsAttempt{frames: [][]byte{liveFrame(t, 100)}})
	r.client.listFn = func(ctx context.Context) ([]docker.ContainerWithDigest, error) {
		c := docker.ContainerWithDigest{}
		c.ID = "abcdef123456"
		c.State = "running"
		return []docker.ContainerWithDigest{c}, nil
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := r.h.StartStatsCollection(ctx); err != nil {
		t.Fatalf("StartStatsCollection: %v", err)
	}
	waitFor(t, "a collector for the unnamed container", func() bool { return r.client.attemptCount() > 0 })
}
