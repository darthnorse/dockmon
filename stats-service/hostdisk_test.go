package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/darthnorse/dockmon-shared/hostdisk"
)

// --- wire presence out of the cache ---

func TestHostStats_NoDiskReadingProducesNoDiskKeys(t *testing.T) {
	data, err := json.Marshal(&HostStats{HostID: "h", CPUPercent: 12.5})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), "disk_") {
		t.Errorf("unset disk reading serialized: %s", data)
	}
}

func TestHostStats_GenuineZeroPercentSerializes(t *testing.T) {
	data, err := json.Marshal(&HostStats{HostID: "h", HostDisk: &hostdisk.HostDisk{DiskSource: "/"}})
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]json.RawMessage
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatal(err)
	}
	if string(decoded["disk_percent"]) != "0" {
		t.Errorf("disk_percent=%s, want 0", decoded["disk_percent"])
	}
	for _, key := range []string{"disk_used_bytes", "disk_available_bytes", "disk_total_bytes", "disk_source"} {
		if _, ok := decoded[key]; !ok {
			t.Errorf("missing %q: %s", key, data)
		}
	}
}

// --- aggregator ---

type fakeHostFS struct {
	stats map[string]hostdisk.Statfs
}

func (f *fakeHostFS) statfs(path string) (hostdisk.Statfs, error) {
	st, ok := f.stats[path]
	if !ok {
		return hostdisk.Statfs{}, syscall.ENOENT
	}
	return st, nil
}

// newTestDiskProber returns a prober whose host root is a verified mount and
// whose filesystems are the given map, keyed by probe path.
func newTestDiskProber(t *testing.T, mounted bool, fs *fakeHostFS) (*hostdisk.Prober, string) {
	t.Helper()
	hostRoot := filepath.Join(t.TempDir(), "hostfs")
	mountinfo := "29 1 0:45 / / rw,relatime - overlay overlay rw\n"
	if mounted {
		mountinfo += "30 29 8:1 / " + hostRoot + " ro,relatime - ext4 /dev/sda1 rw\n"
	}
	path := filepath.Join(t.TempDir(), "mountinfo")
	if err := os.WriteFile(path, []byte(mountinfo), 0o600); err != nil {
		t.Fatal(err)
	}
	p := hostdisk.NewProber(hostRoot)
	p.Statfs = fs.statfs
	p.MountinfoPath = path
	return p, hostRoot
}

var (
	testDataRootFS = hostdisk.Statfs{Blocks: 2000, Bfree: 200, Bavail: 100, Bsize: 4096}
	testHostRootFS = hostdisk.Statfs{Blocks: 1000, Bfree: 800, Bavail: 700, Bsize: 4096}
)

// localHostStreamManager is a registered Docker host whose data-root resolves.
type localHostStreamManager struct {
	dataRoot string
	err      error
}

func (localHostStreamManager) HasHost(string) bool { return true }
func (s localHostStreamManager) DockerRootDir(context.Context, string) (string, error) {
	return s.dataRoot, s.err
}

// newTestHostProcReader points the /host/proc reader at fixture files so the
// host-proc branch runs on a machine without the mount.
func newTestHostProcReader(t *testing.T) *HostProcReader {
	t.Helper()
	dir := t.TempDir()
	files := map[string]string{
		"stat":    "cpu  100 0 100 800 0 0 0 0\n",
		"meminfo": "MemTotal:       16384 kB\nMemAvailable:    8192 kB\n",
	}
	for name, contents := range files {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(contents), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return &HostProcReader{procPath: dir, available: true}
}

func localHostFixture(t *testing.T, hostProc *HostProcReader, prober *hostdisk.Prober, sm streamManagerIface) *Aggregator {
	t.Helper()
	cache := NewStatsCache()
	cache.SetHostLocal("local-1", true)
	cache.containerStats["local-1:aaaaaaaaaaaa"] = &ContainerStats{
		ContainerID: "aaaaaaaaaaaa", HostID: "local-1",
		CPUPercent: 10.0, MemoryUsage: 1024, MemoryLimit: 4096,
		LastUpdate: time.Now(),
	}
	return &Aggregator{
		cache:             cache,
		streamManager:     sm,
		aggregateInterval: time.Second,
		hostProcReader:    hostProc,
		diskProber:        prober,
		diskReaders:       make(map[string]*hostdisk.Reader),
	}
}

func localContainers(agg *Aggregator) []*ContainerStats {
	var out []*ContainerStats
	for _, cs := range agg.cache.GetAllContainerStats() {
		out = append(out, cs)
	}
	return out
}

func TestAggregator_LocalHostDiskMeasuresDataRootAndRidesOnHostProcBranch(t *testing.T) {
	fs := &fakeHostFS{stats: map[string]hostdisk.Statfs{}}
	prober, hostRoot := newTestDiskProber(t, true, fs)
	if err := os.MkdirAll(filepath.Join(hostRoot, "var/lib/docker"), 0o755); err != nil {
		t.Fatal(err)
	}
	fs.stats[filepath.Join(hostRoot, "var/lib/docker")] = testDataRootFS
	fs.stats[hostRoot] = testHostRootFS
	agg := localHostFixture(t, newTestHostProcReader(t), prober, localHostStreamManager{dataRoot: "/var/lib/docker"})

	got := agg.aggregateHostStats("local-1", localContainers(agg), nil)

	if got.HostDisk == nil {
		t.Fatal("local host sample carries no disk reading")
	}
	if got.DiskSource != "/var/lib/docker" {
		t.Errorf("DiskSource=%q, want /var/lib/docker", got.DiskSource)
	}
	if got.DiskTotalBytes != 2000*4096 {
		t.Errorf("DiskTotalBytes=%d, want the data-root filesystem's %d", got.DiskTotalBytes, 2000*4096)
	}
	if got.MemoryLimitBytes != 16384*1024 {
		t.Errorf("MemoryLimitBytes=%d, want the /host/proc reading alongside disk", got.MemoryLimitBytes)
	}
}

// /host/proc unavailable but /hostfs valid: disk still arrives, attached to
// the container-aggregated CPU/memory.
func TestAggregator_LocalHostDiskWithoutHostProc(t *testing.T) {
	fs := &fakeHostFS{stats: map[string]hostdisk.Statfs{}}
	prober, hostRoot := newTestDiskProber(t, true, fs)
	fs.stats[hostRoot] = testHostRootFS
	agg := localHostFixture(t, &HostProcReader{available: false}, prober, localHostStreamManager{dataRoot: "/var/lib/docker"})

	got := agg.aggregateHostStats("local-1", localContainers(agg), nil)

	if got.HostDisk == nil {
		t.Fatal("disk lost because /host/proc is unmounted; the two are independent")
	}
	if got.DiskSource != "/" {
		t.Errorf("DiskSource=%q, want / (data-root absent under the host view)", got.DiskSource)
	}
	if got.MemoryUsedBytes != 1024 {
		t.Errorf("MemoryUsedBytes=%d, want the container aggregate", got.MemoryUsedBytes)
	}
}

// A disk failure must not suppress the CPU/memory reading in the same sample.
func TestAggregator_DiskFailureLeavesCPUAndMemoryIntact(t *testing.T) {
	prober, _ := newTestDiskProber(t, false, &fakeHostFS{stats: map[string]hostdisk.Statfs{}})
	agg := localHostFixture(t, newTestHostProcReader(t), prober, localHostStreamManager{dataRoot: "/var/lib/docker"})

	got := agg.aggregateHostStats("local-1", localContainers(agg), nil)

	if got.HostDisk != nil {
		t.Errorf("disk reported from an unmounted host root: %+v", *got.HostDisk)
	}
	if got.MemoryLimitBytes != 16384*1024 {
		t.Errorf("MemoryLimitBytes=%d, want the /host/proc reading despite the disk failure", got.MemoryLimitBytes)
	}
}

func TestAggregator_NonLocalHostNeverGetsDisk(t *testing.T) {
	fs := &fakeHostFS{stats: map[string]hostdisk.Statfs{}}
	prober, hostRoot := newTestDiskProber(t, true, fs)
	fs.stats[hostRoot] = testHostRootFS
	agg := localHostFixture(t, &HostProcReader{available: false}, prober, localHostStreamManager{dataRoot: "/var/lib/docker"})
	agg.cache.SetHostLocal("local-1", false)

	got := agg.aggregateHostStats("local-1", localContainers(agg), nil)

	if got.HostDisk != nil {
		t.Errorf("the DockMon container's /hostfs was reported as a remote host's disk: %+v", *got.HostDisk)
	}
}

func TestAggregator_NilProberMeansNoDisk(t *testing.T) {
	agg := localHostFixture(t, newTestHostProcReader(t), nil, localHostStreamManager{dataRoot: "/var/lib/docker"})

	got := agg.aggregateHostStats("local-1", localContainers(agg), nil)

	if got.HostDisk != nil {
		t.Errorf("disk fabricated without a prober: %+v", *got.HostDisk)
	}
}

func TestAggregator_UnresolvableDataRootFallsBackToHostRoot(t *testing.T) {
	fs := &fakeHostFS{stats: map[string]hostdisk.Statfs{}}
	prober, hostRoot := newTestDiskProber(t, true, fs)
	fs.stats[hostRoot] = testHostRootFS
	agg := localHostFixture(t, newTestHostProcReader(t), prober, localHostStreamManager{err: errors.New("daemon busy")})

	got := agg.aggregateHostStats("local-1", localContainers(agg), nil)

	if got.HostDisk == nil {
		t.Fatal("no disk reading although the host root is measurable")
	}
	if got.DiskSource != "/" {
		t.Errorf("DiskSource=%q, want /", got.DiskSource)
	}
}

// A valid reading followed by a failed one must clear the cached values, not
// leave a last-known-good number for alerts to keep firing on.
func TestAggregator_StaleDiskIsClearedFromTheCache(t *testing.T) {
	fs := &fakeHostFS{stats: map[string]hostdisk.Statfs{}}
	prober, hostRoot := newTestDiskProber(t, true, fs)
	fs.stats[hostRoot] = testHostRootFS
	agg := localHostFixture(t, newTestHostProcReader(t), prober, localHostStreamManager{dataRoot: "/var/lib/docker"})

	agg.aggregate()
	first, ok := agg.cache.GetHostStats("local-1")
	if !ok || first.HostDisk == nil {
		t.Fatalf("first cycle produced no disk reading: %+v", first)
	}

	delete(fs.stats, hostRoot)
	agg.aggregate()

	second, ok := agg.cache.GetHostStats("local-1")
	if !ok {
		t.Fatal("host entry vanished")
	}
	if second.HostDisk != nil {
		t.Errorf("stale disk reading survived a failed read: %+v", *second.HostDisk)
	}
	if second.MemoryLimitBytes == 0 {
		t.Error("CPU/memory were dropped along with disk")
	}
}

func TestAggregator_DropsDiskReaderWhenHostStopsBeingLocal(t *testing.T) {
	fs := &fakeHostFS{stats: map[string]hostdisk.Statfs{}}
	prober, hostRoot := newTestDiskProber(t, true, fs)
	fs.stats[hostRoot] = testHostRootFS
	agg := localHostFixture(t, newTestHostProcReader(t), prober, localHostStreamManager{dataRoot: "/var/lib/docker"})

	agg.aggregate()
	if _, ok := agg.diskReaders["local-1"]; !ok {
		t.Fatal("no reader created for the local host")
	}

	agg.cache.RemoveHostStats("local-1")
	agg.aggregate()

	if _, ok := agg.diskReaders["local-1"]; ok {
		t.Error("reader for a removed host was kept")
	}
}
