package handlers

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/darthnorse/dockmon-agent/internal/client/statsmsg"
	"github.com/darthnorse/dockmon-shared/hostdisk"
	"github.com/sirupsen/logrus"
)

type fakeStatsSender struct {
	mu   sync.Mutex
	sent []statsmsg.AgentStatsMsg
}

func (f *fakeStatsSender) Send(msg statsmsg.AgentStatsMsg) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.sent = append(f.sent, msg)
}

func (f *fakeStatsSender) messages() []statsmsg.AgentStatsMsg {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]statsmsg.AgentStatsMsg(nil), f.sent...)
}

// newTestHostStatsHandler builds a handler reading from a temp proc directory.
// procContents maps file name -> contents; a missing file reproduces a read
// failure.
func newTestHostStatsHandler(t *testing.T, procContents map[string]string) (*HostStatsHandler, *[]map[string]interface{}) {
	t.Helper()
	procDir := t.TempDir()
	for name, contents := range procContents {
		if err := os.WriteFile(filepath.Join(procDir, name), []byte(contents), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	log := logrus.New()
	log.SetOutput(io.Discard)

	var sent []map[string]interface{}
	h := NewHostStatsHandler(log, func(payload interface{}) error {
		if m, ok := payload.(map[string]interface{}); ok {
			sent = append(sent, m)
		}
		return nil
	}, nil)
	h.procPath = procDir
	h.sysPath = filepath.Join(procDir, "no-sys")
	return h, &sent
}

const testProcStat = "cpu  100 0 100 800 0 0 0 0\ncpu0 100 0 100 800 0 0 0 0\n"

// primeCPU seeds the previous CPU counters so collect() has a delta to work
// with; without it the first read is a baseline and publishes nothing.
func primeCPU(h *HostStatsHandler) {
	h.prevCPU = cpuStats{user: 50, system: 50, idle: 400}
}

func writeProcFile(t *testing.T, h *HostStatsHandler, name, contents string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(h.procPath, name), []byte(contents), 0o600); err != nil {
		t.Fatal(err)
	}
}

// /proc/meminfo reports kB. Publishing the raw values as bytes would
// under-report memory by 1024x.
func TestHostStatsHandler_MemoryBytesConvertedFromKB(t *testing.T) {
	h, _ := newTestHostStatsHandler(t, map[string]string{
		"stat":    testProcStat,
		"meminfo": "MemTotal:       16384 kB\nMemAvailable:    8192 kB\n",
	})

	mem, err := h.readMemory()
	if err != nil {
		t.Fatalf("readMemory: %v", err)
	}
	if mem.totalBytes != 16384*1024 {
		t.Errorf("totalBytes=%d, want %d", mem.totalBytes, 16384*1024)
	}
	if mem.usedBytes != 8192*1024 {
		t.Errorf("usedBytes=%d, want %d", mem.usedBytes, 8192*1024)
	}
	if mem.percent != 50 {
		t.Errorf("percent=%v, want 50", mem.percent)
	}
}

// A zero-valued sample from a failed /proc read looks exactly like a healthy
// idle host, so no sample must be published at all.
func TestHostStatsHandler_NoSampleWhenProcReadFails(t *testing.T) {
	cases := map[string]map[string]string{
		"missing meminfo": {"stat": testProcStat},
		"missing stat":    {"meminfo": "MemTotal: 16384 kB\nMemAvailable: 8192 kB\n"},
		"empty proc":      {},
	}

	for name, contents := range cases {
		t.Run(name, func(t *testing.T) {
			h, sent := newTestHostStatsHandler(t, contents)
			primeCPU(h)
			sender := &fakeStatsSender{}
			h.SetStatsServiceClient(sender)

			h.collect(context.Background())

			if len(*sent) != 0 {
				t.Errorf("published %d control-WS samples, want 0: %v", len(*sent), *sent)
			}
			if n := len(sender.messages()); n != 0 {
				t.Errorf("dual-sent %d samples, want 0", n)
			}
		})
	}
}

// A malformed meminfo (no MemTotal) is a read failure, not a 0%% host.
func TestHostStatsHandler_NoSampleWhenMemTotalMissing(t *testing.T) {
	h, sent := newTestHostStatsHandler(t, map[string]string{
		"stat":    testProcStat,
		"meminfo": "Buffers:  1234 kB\n",
	})
	primeCPU(h)
	sender := &fakeStatsSender{}
	h.SetStatsServiceClient(sender)

	h.collect(context.Background())

	if len(*sent) != 0 {
		t.Errorf("published %d control-WS samples, want 0", len(*sent))
	}
	if n := len(sender.messages()); n != 0 {
		t.Errorf("dual-sent %d samples, want 0", n)
	}
}

// The first /proc/stat read only seeds the counters, so its 0% is unknown
// utilisation, not idle. Publishing it could clear a live host CPU alert on
// every agent restart.
func TestHostStatsHandler_SkipsCPUBaselineSample(t *testing.T) {
	h, sent := newTestHostStatsHandler(t, map[string]string{
		"stat":    testProcStat,
		"meminfo": "MemTotal:       16384 kB\nMemAvailable:    8192 kB\n",
	})
	sender := &fakeStatsSender{}
	h.SetStatsServiceClient(sender)

	h.collect(context.Background()) // baseline

	if len(*sent) != 0 {
		t.Errorf("published %d control-WS samples on the baseline pass, want 0: %v", len(*sent), *sent)
	}
	if n := len(sender.messages()); n != 0 {
		t.Errorf("dual-sent %d samples on the baseline pass, want 0", n)
	}

	// Second pass has a delta to work with and must publish.
	writeProcFile(t, h, "stat", "cpu  200 0 200 1600 0 0 0 0\n")
	h.collect(context.Background())

	if len(*sent) != 1 {
		t.Errorf("control-WS samples after the second pass=%d, want 1", len(*sent))
	}
	if n := len(sender.messages()); n != 1 {
		t.Errorf("dual-sent %d samples after the second pass, want 1", n)
	}
}

func TestHostStatsHandler_DualSendsHostStats(t *testing.T) {
	h, sent := newTestHostStatsHandler(t, map[string]string{
		"stat":    testProcStat,
		"meminfo": "MemTotal:       16384 kB\nMemAvailable:    8192 kB\n",
	})
	primeCPU(h)
	sender := &fakeStatsSender{}
	h.SetStatsServiceClient(sender)

	h.collect(context.Background())

	if len(*sent) != 1 {
		t.Fatalf("control-WS samples=%d, want 1", len(*sent))
	}
	msgs := sender.messages()
	if len(msgs) != 1 {
		t.Fatalf("dual-sent %d samples, want 1", len(msgs))
	}

	m := msgs[0]
	if m.Type != statsmsg.TypeHostStats {
		t.Errorf("Type=%q, want %q", m.Type, statsmsg.TypeHostStats)
	}
	if m.ContainerID != "" {
		t.Errorf("ContainerID=%q, want empty (host sample)", m.ContainerID)
	}
	if m.MemoryPercent != 50 {
		t.Errorf("MemoryPercent=%v, want 50", m.MemoryPercent)
	}
	if m.MemoryUsedBytes != 8192*1024 {
		t.Errorf("MemoryUsedBytes=%d, want %d", m.MemoryUsedBytes, 8192*1024)
	}
	if m.MemoryLimitBytes != 16384*1024 {
		t.Errorf("MemoryLimitBytes=%d, want %d", m.MemoryLimitBytes, 16384*1024)
	}
	if m.Timestamp == "" {
		t.Error("Timestamp empty")
	}
}

// The control-WS payload keeps its own field names; the evaluator reads
// memory_percent off the ingest wire, so the two must not be confused.
func TestHostStatsHandler_ControlWSKeepsMemPercentField(t *testing.T) {
	h, sent := newTestHostStatsHandler(t, map[string]string{
		"stat":    testProcStat,
		"meminfo": "MemTotal:       16384 kB\nMemAvailable:    8192 kB\n",
	})
	primeCPU(h)

	h.collect(context.Background())

	if len(*sent) != 1 {
		t.Fatalf("control-WS samples=%d, want 1", len(*sent))
	}
	stats, ok := (*sent)[0]["stats"].(map[string]interface{})
	if !ok {
		t.Fatalf("control-WS payload has no stats map: %v", (*sent)[0])
	}
	if _, ok := stats["mem_percent"]; !ok {
		t.Errorf("control-WS payload lost mem_percent: %v", stats)
	}
}

func TestHostStatsHandler_NoDualSendWhenUnattached(t *testing.T) {
	h, sent := newTestHostStatsHandler(t, map[string]string{
		"stat":    testProcStat,
		"meminfo": "MemTotal:       16384 kB\nMemAvailable:    8192 kB\n",
	})
	primeCPU(h)

	h.collect(context.Background()) // must not panic

	if len(*sent) != 1 {
		t.Errorf("control-WS samples=%d, want 1", len(*sent))
	}
}

// Typed-nil in an interface would pass a `!= nil` check and panic on send.
func TestHostStatsHandler_SetStatsServiceClientNilSafe(t *testing.T) {
	h, _ := newTestHostStatsHandler(t, map[string]string{
		"stat":    testProcStat,
		"meminfo": "MemTotal:       16384 kB\nMemAvailable:    8192 kB\n",
	})

	var typedNil *fakeStatsSender
	h.SetStatsServiceClient(typedNil)
	if h.statsService != nil {
		t.Error("typed-nil sender was not normalized to a strict nil")
	}

	h.SetStatsServiceClient(&fakeStatsSender{})
	if h.statsService == nil {
		t.Fatal("real sender was not stored")
	}

	h.SetStatsServiceClient(nil)
	if h.statsService != nil {
		t.Error("nil did not disable dual-send")
	}
}

// --- host disk (Fix D) ---

type fakeDiskReader struct {
	reading *hostdisk.Reading
	err     error
	calls   int
}

func (f *fakeDiskReader) Read(context.Context) (*hostdisk.Reading, error) {
	f.calls++
	return f.reading, f.err
}

const testMeminfo = "MemTotal:       16384 kB\nMemAvailable:    8192 kB\n"

func TestHostStatsHandler_DiskReadingRidesOnTheHostSample(t *testing.T) {
	h, _ := newTestHostStatsHandler(t, map[string]string{"stat": testProcStat, "meminfo": testMeminfo})
	primeCPU(h)
	sender := &fakeStatsSender{}
	h.SetStatsServiceClient(sender)
	h.disk = &fakeDiskReader{reading: &hostdisk.Reading{
		Percent: 54.7, UsedBytes: 100, AvailableBytes: 80, TotalBytes: 200, Source: "/var/lib/docker",
	}}

	h.collect(context.Background())

	msgs := sender.messages()
	if len(msgs) != 1 {
		t.Fatalf("dual-sent %d samples, want 1", len(msgs))
	}
	d := msgs[0].HostDisk
	if d == nil {
		t.Fatal("host sample carries no disk reading")
	}
	if d.DiskPercent != 54.7 || d.DiskUsedBytes != 100 || d.DiskAvailableBytes != 80 || d.DiskTotalBytes != 200 || d.DiskSource != "/var/lib/docker" {
		t.Errorf("disk fields=%+v, want the reading verbatim", *d)
	}
	if msgs[0].MemoryPercent != 50 {
		t.Errorf("MemoryPercent=%v, want 50 alongside disk", msgs[0].MemoryPercent)
	}
}

// A disk failure omits the disk fields; it must not silence host CPU and
// memory alerting, which already works.
func TestHostStatsHandler_DiskErrorLeavesCPUAndMemoryIntact(t *testing.T) {
	h, sent := newTestHostStatsHandler(t, map[string]string{"stat": testProcStat, "meminfo": testMeminfo})
	primeCPU(h)
	sender := &fakeStatsSender{}
	h.SetStatsServiceClient(sender)
	h.disk = &fakeDiskReader{err: hostdisk.ErrHostRootNotMounted}

	h.collect(context.Background())

	if len(*sent) != 1 {
		t.Errorf("control-WS samples=%d, want 1 despite the disk failure", len(*sent))
	}
	msgs := sender.messages()
	if len(msgs) != 1 {
		t.Fatalf("dual-sent %d samples, want 1 despite the disk failure", len(msgs))
	}
	if msgs[0].HostDisk != nil {
		t.Errorf("disk fields present after a read failure: %+v", *msgs[0].HostDisk)
	}
	if msgs[0].MemoryPercent != 50 {
		t.Errorf("MemoryPercent=%v, want 50", msgs[0].MemoryPercent)
	}
}

func TestHostStatsHandler_NoDiskReaderMeansNoDiskFields(t *testing.T) {
	h, _ := newTestHostStatsHandler(t, map[string]string{"stat": testProcStat, "meminfo": testMeminfo})
	primeCPU(h)
	sender := &fakeStatsSender{}
	h.SetStatsServiceClient(sender)

	h.collect(context.Background())

	msgs := sender.messages()
	if len(msgs) != 1 {
		t.Fatalf("dual-sent %d samples, want 1", len(msgs))
	}
	if msgs[0].HostDisk != nil {
		t.Errorf("disk fields fabricated without a reader: %+v", *msgs[0].HostDisk)
	}
}

// Disk is not read on a pass that publishes nothing: the host sample is the
// only carrier, so probing without one is wasted work.
func TestHostStatsHandler_DiskNotReadWhenSampleIsSkipped(t *testing.T) {
	h, _ := newTestHostStatsHandler(t, map[string]string{"stat": testProcStat})
	primeCPU(h)
	disk := &fakeDiskReader{reading: &hostdisk.Reading{Percent: 1}}
	h.disk = disk

	h.collect(context.Background())

	if disk.calls != 0 {
		t.Errorf("disk read %d times on an unpublished pass, want 0", disk.calls)
	}
}
