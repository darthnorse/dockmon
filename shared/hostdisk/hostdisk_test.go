package hostdisk

import (
	"context"
	"errors"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

// Real numbers from this machine's root filesystem on 2026-09-15: df said
// 55% while used/size said 51.9%, because 4.9G is root-reserved.
var rootFS = Statfs{Blocks: 25_141_000, Bfree: 12_090_000, Bavail: 10_805_000, Bsize: 4096, Frsize: 4096}

func TestCompute_MatchesDfNotNaiveRatio(t *testing.T) {
	r, err := Compute(rootFS)
	if err != nil {
		t.Fatal(err)
	}
	used := float64(rootFS.Blocks-rootFS.Bfree) * 4096
	avail := float64(rootFS.Bavail) * 4096
	wantDf := used / (used + avail) * 100
	naive := used / (float64(rootFS.Blocks) * 4096) * 100

	if math.Abs(r.Percent-wantDf) > 1e-9 {
		t.Errorf("Percent=%.3f, want df's %.3f", r.Percent, wantDf)
	}
	if math.Abs(r.Percent-naive) < 1 {
		t.Errorf("Percent=%.3f is the naive used/size ratio %.3f, which under-reports fullness", r.Percent, naive)
	}
}

// The UI must be able to regenerate the percentage from the bytes it is
// shown, or it contradicts the alert beside it.
func TestCompute_BytesReproducePercentAndKeepTrueTotal(t *testing.T) {
	r, err := Compute(rootFS)
	if err != nil {
		t.Fatal(err)
	}
	regen := float64(r.UsedBytes) / float64(r.UsedBytes+r.AvailableBytes) * 100
	if math.Abs(regen-r.Percent) > 1e-9 {
		t.Errorf("used/(used+available)=%.6f, Percent=%.6f", regen, r.Percent)
	}
	if r.TotalBytes != rootFS.Blocks*4096 {
		t.Errorf("TotalBytes=%d, want the true size %d", r.TotalBytes, rootFS.Blocks*4096)
	}
	if r.UsedBytes+r.AvailableBytes >= r.TotalBytes {
		t.Error("reserved blocks vanished: used+available should be below total on this filesystem")
	}
}

func TestCompute_UsesFrsizeOverBsize(t *testing.T) {
	r, err := Compute(Statfs{Blocks: 1000, Bfree: 500, Bavail: 500, Bsize: 4096, Frsize: 1024})
	if err != nil {
		t.Fatal(err)
	}
	if r.TotalBytes != 1000*1024 {
		t.Errorf("TotalBytes=%d, want %d (Frsize units)", r.TotalBytes, 1000*1024)
	}
}

func TestCompute_FallsBackToBsizeWhenFrsizeZero(t *testing.T) {
	r, err := Compute(Statfs{Blocks: 1000, Bfree: 500, Bavail: 500, Bsize: 4096})
	if err != nil {
		t.Fatal(err)
	}
	if r.TotalBytes != 1000*4096 {
		t.Errorf("TotalBytes=%d, want %d", r.TotalBytes, 1000*4096)
	}
}

func TestCompute_GenuinelyEmptyIsZeroPercent(t *testing.T) {
	r, err := Compute(Statfs{Blocks: 1000, Bfree: 1000, Bavail: 1000, Bsize: 4096})
	if err != nil {
		t.Fatal(err)
	}
	if r.Percent != 0 || r.UsedBytes != 0 {
		t.Errorf("empty filesystem: Percent=%v UsedBytes=%d, want 0/0", r.Percent, r.UsedBytes)
	}
}

func TestCompute_FullIsHundredPercent(t *testing.T) {
	r, err := Compute(Statfs{Blocks: 1000, Bfree: 0, Bavail: 0, Bsize: 4096})
	if err != nil {
		t.Fatal(err)
	}
	if r.Percent != 100 {
		t.Errorf("Percent=%v, want 100", r.Percent)
	}
}

// Reserved blocks are the difference between Bfree and Bavail. A filesystem
// with only reserved space left is full to a non-root writer.
func TestCompute_OnlyReservedSpaceLeftIsFull(t *testing.T) {
	r, err := Compute(Statfs{Blocks: 1000, Bfree: 50, Bavail: 0, Bsize: 4096})
	if err != nil {
		t.Fatal(err)
	}
	if r.Percent != 100 {
		t.Errorf("Percent=%v, want 100 (only root-reserved blocks remain)", r.Percent)
	}
}

// Unsigned inconsistencies must surface as errors, never as an enormous
// plausible number or a healthy-looking small one.
func TestCompute_RejectsInconsistentStatfs(t *testing.T) {
	cases := map[string]Statfs{
		"zero blocks":          {Blocks: 0, Bfree: 0, Bavail: 0, Bsize: 4096},
		"zero block size":      {Blocks: 1000, Bfree: 500, Bavail: 500},
		"bfree above blocks":   {Blocks: 1000, Bfree: 1001, Bavail: 500, Bsize: 4096},
		"bavail above bfree":   {Blocks: 1000, Bfree: 500, Bavail: 900, Bsize: 4096},
		"all blocks reserved":  {Blocks: 1000, Bfree: 1000, Bavail: 0, Bsize: 4096},
		"total overflows uint": {Blocks: math.MaxUint64 / 2, Bfree: 1, Bavail: 1, Bsize: 4096},
	}
	for name, st := range cases {
		t.Run(name, func(t *testing.T) {
			r, err := Compute(st)
			if err == nil {
				t.Fatalf("Compute accepted inconsistent statfs and produced %+v", r)
			}
			if !errors.Is(err, ErrInvalidStatfs) {
				t.Errorf("err=%v, want ErrInvalidStatfs", err)
			}
		})
	}
}

// Cross-check against the real statfs(2) and df on this machine so the
// formula is pinned to the tool operators compare against.
func TestCompute_AgreesWithDfOnRealFilesystem(t *testing.T) {
	if _, err := exec.LookPath("df"); err != nil {
		t.Skip("df not available")
	}
	dir := t.TempDir()
	st, err := statfs(dir)
	if err != nil {
		t.Fatal(err)
	}
	r, err := Compute(st)
	if err != nil {
		t.Fatal(err)
	}

	out, err := exec.Command("df", "-P", dir).Output()
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(out)), "\n")
	fields := strings.Fields(lines[len(lines)-1])
	dfPct, err := strconv.Atoi(strings.TrimSuffix(fields[4], "%"))
	if err != nil {
		t.Fatalf("df output %q: %v", lines[len(lines)-1], err)
	}
	// df rounds up; a live filesystem may move a little between the two reads.
	if got := int(math.Ceil(r.Percent)); got < dfPct-1 || got > dfPct+1 {
		t.Errorf("ceil(Percent)=%d, df says %d%% (Percent=%.3f)", got, dfPct, r.Percent)
	}
}

// --- mount verification ---

const mountinfoWithHostfs = `22 29 0:21 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw
29 1 0:45 / / rw,relatime - overlay overlay rw,lowerdir=/a,upperdir=/b
30 29 8:1 / /hostfs ro,relatime - ext4 /dev/sda1 rw
31 30 0:24 / /hostfs/tmp rw,nosuid - tmpfs tmpfs rw
`

const mountinfoWithoutHostfs = `22 29 0:21 / /proc rw,nosuid,nodev,noexec,relatime - proc proc rw
29 1 0:45 / / rw,relatime - overlay overlay rw,lowerdir=/a,upperdir=/b
32 29 8:1 / /hostfs-other ro,relatime - ext4 /dev/sda1 rw
33 29 8:1 / /data/hostfs ro,relatime - ext4 /dev/sda1 rw
`

func writeMountinfo(t *testing.T, contents string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "mountinfo")
	if err := os.WriteFile(path, []byte(contents), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestIsMountPoint(t *testing.T) {
	cases := []struct {
		name      string
		mountinfo string
		want      bool
	}{
		{"real bind", mountinfoWithHostfs, true},
		{"bare directory, prefix and suffix matches only", mountinfoWithoutHostfs, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := isMountPoint(writeMountinfo(t, tc.mountinfo), "/hostfs")
			if err != nil {
				t.Fatal(err)
			}
			if got != tc.want {
				t.Errorf("isMountPoint=%v, want %v", got, tc.want)
			}
		})
	}
}

// Mount points with spaces are octal-escaped in mountinfo.
func TestIsMountPoint_DecodesEscapes(t *testing.T) {
	path := writeMountinfo(t, "40 29 8:1 / /host\\040fs ro,relatime - ext4 /dev/sda1 rw\n")
	got, err := isMountPoint(path, "/host fs")
	if err != nil {
		t.Fatal(err)
	}
	if !got {
		t.Error("escaped mount point was not decoded")
	}
}

func TestIsMountPoint_UnreadableMountinfoIsAnError(t *testing.T) {
	_, err := isMountPoint(filepath.Join(t.TempDir(), "missing"), "/hostfs")
	if err == nil {
		t.Fatal("expected an error for an unreadable mountinfo, got nil (would fail open)")
	}
}

// --- Prober ---

type fakeFS struct {
	stats map[string]Statfs
	calls []string
}

func (f *fakeFS) statfs(path string) (Statfs, error) {
	f.calls = append(f.calls, path)
	st, ok := f.stats[path]
	if !ok {
		return Statfs{}, syscall.ENOENT
	}
	return st, nil
}

var (
	dataRootFS = Statfs{Blocks: 2000, Bfree: 200, Bavail: 100, Bsize: 4096}
	hostRootFS = Statfs{Blocks: 1000, Bfree: 800, Bavail: 700, Bsize: 4096}
)

// newHostRoot builds a fake host root on disk containing the given host paths
// (directories) and returns it with a mountinfo naming it as a mount point.
func newHostRoot(t *testing.T, dirs ...string) (hostRoot, mountinfo string) {
	t.Helper()
	hostRoot = filepath.Join(t.TempDir(), "hostfs")
	for _, d := range append([]string{"/"}, dirs...) {
		if err := os.MkdirAll(filepath.Join(hostRoot, d), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	mountinfo = "29 1 0:45 / / rw,relatime - overlay overlay rw\n" +
		"30 29 8:1 / " + hostRoot + " ro,relatime - ext4 /dev/sda1 rw\n"
	return hostRoot, mountinfo
}

func newProber(t *testing.T, hostRoot string, fs *fakeFS, mountinfo string) *Prober {
	t.Helper()
	p := NewProber(hostRoot)
	p.Statfs = fs.statfs
	p.MountinfoPath = writeMountinfo(t, mountinfo)
	return p
}

func TestProber_ContainerModeMeasuresDataRootUnderHostfs(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t, "/var/lib/docker")
	fs := &fakeFS{stats: map[string]Statfs{
		filepath.Join(hostRoot, "var/lib/docker"): dataRootFS,
		hostRoot: hostRootFS,
	}}
	p := newProber(t, hostRoot, fs, mountinfo)

	r, err := p.Probe("/var/lib/docker")
	if err != nil {
		t.Fatal(err)
	}
	if r.TotalBytes != 2000*4096 {
		t.Errorf("measured %d bytes total, want the data-root filesystem (%d)", r.TotalBytes, 2000*4096)
	}
	if r.Source != "/var/lib/docker" {
		t.Errorf("Source=%q, want the logical host path /var/lib/docker, never the probe path", r.Source)
	}
	if len(fs.calls) == 0 || fs.calls[0] != filepath.Join(hostRoot, "var/lib/docker") {
		t.Errorf("statfs calls=%v, want the first under the host root", fs.calls)
	}
}

func TestProber_SystemdModeUsesDirectPath(t *testing.T) {
	dataRoot := t.TempDir()
	fs := &fakeFS{stats: map[string]Statfs{
		dataRoot: dataRootFS,
		"/":      hostRootFS,
	}}
	p := NewProber("")
	p.Statfs = fs.statfs
	p.MountinfoPath = filepath.Join(t.TempDir(), "never-read")

	r, err := p.Probe(dataRoot)
	if err != nil {
		t.Fatal(err)
	}
	if r.Source != dataRoot || r.TotalBytes != 2000*4096 {
		t.Errorf("got %+v, want the data-root reading via the direct path", r)
	}
}

func TestProber_MissingDataRootFallsBackToHostRootAndSaysSo(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t)
	fs := &fakeFS{stats: map[string]Statfs{hostRoot: hostRootFS}}
	p := newProber(t, hostRoot, fs, mountinfo)

	r, err := p.Probe("/mnt/remote/docker")
	if err != nil {
		t.Fatalf("a data-root absent under the host view must fall back, got %v", err)
	}
	if r.TotalBytes != 1000*4096 {
		t.Errorf("TotalBytes=%d, want the host root's %d", r.TotalBytes, 1000*4096)
	}
	if r.Source != "/" {
		t.Errorf("Source=%q, want \"/\" so the fallback is distinguishable from the real thing", r.Source)
	}
}

// The common way to move Docker to a bigger disk is an absolute symlink at
// /var/lib/docker. Under /hostfs the kernel would resolve that target against
// the container's root, so it has to be re-rooted onto the host view.
func TestProber_AbsoluteSymlinkedDataRootResolvesUnderHostRoot(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t, "/var/lib", "/mnt/bigdisk/docker")
	if err := os.Symlink("/mnt/bigdisk/docker", filepath.Join(hostRoot, "var/lib/docker")); err != nil {
		t.Fatal(err)
	}
	fs := &fakeFS{stats: map[string]Statfs{
		filepath.Join(hostRoot, "mnt/bigdisk/docker"): dataRootFS,
		hostRoot: hostRootFS,
	}}
	p := newProber(t, hostRoot, fs, mountinfo)

	r, err := p.Probe("/var/lib/docker")
	if err != nil {
		t.Fatal(err)
	}
	if r.TotalBytes != 2000*4096 {
		t.Errorf("TotalBytes=%d, want the symlink target's filesystem (%d); Source=%q", r.TotalBytes, 2000*4096, r.Source)
	}
	if r.Source != "/var/lib/docker" {
		t.Errorf("Source=%q, want the data-root as Docker names it", r.Source)
	}
	for _, c := range fs.calls {
		if !strings.HasPrefix(c, hostRoot) {
			t.Errorf("statfs escaped the host root: %v", fs.calls)
		}
	}
}

func TestProber_RelativeSymlinkInDataRootPathIsFollowed(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t, "/var/lib", "/var/docker-data")
	if err := os.Symlink("../docker-data", filepath.Join(hostRoot, "var/lib/docker")); err != nil {
		t.Fatal(err)
	}
	fs := &fakeFS{stats: map[string]Statfs{
		filepath.Join(hostRoot, "var/docker-data"): dataRootFS,
		hostRoot: hostRootFS,
	}}
	p := newProber(t, hostRoot, fs, mountinfo)

	r, err := p.Probe("/var/lib/docker")
	if err != nil {
		t.Fatal(err)
	}
	if r.TotalBytes != 2000*4096 {
		t.Errorf("TotalBytes=%d, want the symlink target's filesystem", r.TotalBytes)
	}
}

func TestProber_SymlinkLoopFallsBackToHostRoot(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t, "/var/lib")
	if err := os.Symlink("/var/lib/docker", filepath.Join(hostRoot, "var/lib/docker")); err != nil {
		t.Fatal(err)
	}
	fs := &fakeFS{stats: map[string]Statfs{hostRoot: hostRootFS}}
	p := newProber(t, hostRoot, fs, mountinfo)

	r, err := p.Probe("/var/lib/docker")
	if err != nil {
		t.Fatal(err)
	}
	if r.Source != "/" {
		t.Errorf("Source=%q, want / after a symlink loop", r.Source)
	}
}

func TestProber_DotDotInDataRootCannotClimbAboveHostRoot(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t)
	fs := &fakeFS{stats: map[string]Statfs{hostRoot: hostRootFS}}
	p := newProber(t, hostRoot, fs, mountinfo)

	if _, err := p.Probe("/../../etc"); err != nil {
		t.Fatal(err)
	}
	for _, c := range fs.calls {
		if !strings.HasPrefix(c, hostRoot) {
			t.Errorf("statfs escaped the host root: %v", fs.calls)
		}
	}
}

func TestProber_EmptyDataRootMeasuresHostRoot(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t)
	fs := &fakeFS{stats: map[string]Statfs{hostRoot: hostRootFS}}
	p := newProber(t, hostRoot, fs, mountinfo)

	r, err := p.Probe("")
	if err != nil {
		t.Fatal(err)
	}
	if r.Source != "/" {
		t.Errorf("Source=%q, want /", r.Source)
	}
}

func TestProber_RelativeDataRootIsIgnored(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t, "/var/lib/docker")
	fs := &fakeFS{stats: map[string]Statfs{hostRoot: hostRootFS}}
	p := newProber(t, hostRoot, fs, mountinfo)

	r, err := p.Probe("var/lib/docker")
	if err != nil {
		t.Fatal(err)
	}
	if r.Source != "/" {
		t.Errorf("Source=%q, want / (relative data-root cannot be resolved)", r.Source)
	}
	for _, c := range fs.calls {
		if strings.Contains(c, "var/lib/docker") {
			t.Errorf("relative data-root was probed: %v", fs.calls)
		}
	}
}

// The trap this phase exists for: a bare `mkdir /hostfs` makes Statfs
// succeed and report the container's own overlay as the host's disk.
func TestProber_HostfsDirectoryThatIsNotAMountYieldsNothing(t *testing.T) {
	hostRoot, _ := newHostRoot(t, "/var/lib/docker")
	fs := &fakeFS{stats: map[string]Statfs{
		hostRoot: {Blocks: 1000, Bfree: 800, Bavail: 700, Bsize: 4096},
		filepath.Join(hostRoot, "var/lib/docker"): {Blocks: 1000, Bfree: 800, Bavail: 700, Bsize: 4096},
	}}
	p := newProber(t, hostRoot, fs, mountinfoWithoutHostfs)

	r, err := p.Probe("/var/lib/docker")
	if err == nil {
		t.Fatalf("Probe returned %+v from an unmounted /hostfs: that is the container's own disk", r)
	}
	if !errors.Is(err, ErrHostRootNotMounted) {
		t.Errorf("err=%v, want ErrHostRootNotMounted", err)
	}
	if len(fs.calls) != 0 {
		t.Errorf("statfs was called (%v) before the mount was verified", fs.calls)
	}
}

func TestProber_UnreadableMountinfoFailsClosed(t *testing.T) {
	hostRoot, _ := newHostRoot(t)
	fs := &fakeFS{stats: map[string]Statfs{hostRoot: hostRootFS}}
	p := NewProber(hostRoot)
	p.Statfs = fs.statfs
	p.MountinfoPath = filepath.Join(t.TempDir(), "missing")

	if _, err := p.Probe(""); err == nil {
		t.Fatal("Probe succeeded without being able to verify the mount")
	}
}

func TestProber_HostRootStatfsErrorIsReturned(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t)
	fs := &fakeFS{stats: map[string]Statfs{}}
	p := newProber(t, hostRoot, fs, mountinfo)

	if _, err := p.Probe("/var/lib/docker"); err == nil {
		t.Fatal("Probe succeeded with no measurable filesystem")
	}
}

func TestProber_InconsistentDataRootFallsBackToHostRoot(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t, "/var/lib/docker")
	fs := &fakeFS{stats: map[string]Statfs{
		filepath.Join(hostRoot, "var/lib/docker"): {Blocks: 0},
		hostRoot: hostRootFS,
	}}
	p := newProber(t, hostRoot, fs, mountinfo)

	r, err := p.Probe("/var/lib/docker")
	if err != nil {
		t.Fatal(err)
	}
	if r.Source != "/" {
		t.Errorf("Source=%q, want / after the data-root reading was rejected", r.Source)
	}
}

// --- Reader ---

func TestReader_ResolvesDataRootOnceAndRetriesAfterFailure(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t, "/var/lib/docker")
	fs := &fakeFS{stats: map[string]Statfs{
		filepath.Join(hostRoot, "var/lib/docker"): dataRootFS,
		hostRoot: hostRootFS,
	}}
	p := newProber(t, hostRoot, fs, mountinfo)

	resolves := 0
	fail := true
	reader := NewReader(p, func(context.Context) (string, error) {
		resolves++
		if fail {
			return "", errors.New("daemon not ready")
		}
		return "/var/lib/docker", nil
	}, nil)
	clock := time.Now()
	reader.now = func() time.Time { return clock }

	r, err := reader.Read(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if r.Source != "/" {
		t.Errorf("Source=%q, want / while the data-root is unresolved", r.Source)
	}

	fail = false
	clock = clock.Add(resolveRetryInterval + time.Second)
	for i := 0; i < 3; i++ {
		r, err = reader.Read(context.Background())
		if err != nil {
			t.Fatal(err)
		}
	}
	if r.Source != "/var/lib/docker" {
		t.Errorf("Source=%q, want the data-root once resolvable", r.Source)
	}
	if resolves != 2 {
		t.Errorf("data-root resolved %d times, want 2 (one failure, one success, then memoized)", resolves)
	}
}

// A slow-but-alive daemon must not be asked again on every sampling tick: the
// lookup runs synchronously in the caller's loop.
func TestReader_BacksOffDataRootResolutionAfterFailure(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t)
	fs := &fakeFS{stats: map[string]Statfs{hostRoot: hostRootFS}}
	p := newProber(t, hostRoot, fs, mountinfo)

	resolves := 0
	reader := NewReader(p, func(context.Context) (string, error) {
		resolves++
		return "", errors.New("daemon slow")
	}, nil)
	clock := time.Now()
	reader.now = func() time.Time { return clock }

	for i := 0; i < 5; i++ {
		if _, err := reader.Read(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if resolves != 1 {
		t.Fatalf("resolver called %d times within the backoff window, want 1", resolves)
	}

	clock = clock.Add(resolveRetryInterval + time.Second)
	if _, err := reader.Read(context.Background()); err != nil {
		t.Fatal(err)
	}
	if resolves != 2 {
		t.Errorf("resolver called %d times after the window, want 2", resolves)
	}
}

// Falling back from a resolved data-root to the host root is a different disk
// than the operator asked about; it must be said once, not silently.
func TestReader_WarnsOnceWhenDataRootFallsBackToHostRoot(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t)
	fs := &fakeFS{stats: map[string]Statfs{hostRoot: hostRootFS}}
	p := newProber(t, hostRoot, fs, mountinfo)

	var warnings []string
	reader := NewReader(p, func(context.Context) (string, error) {
		return "/mnt/remote/docker", nil
	}, func(format string, args ...interface{}) {
		warnings = append(warnings, fmt.Sprintf(format, args...))
	})

	for i := 0; i < 3; i++ {
		r, err := reader.Read(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		if r.Source != "/" {
			t.Fatalf("Source=%q, want /", r.Source)
		}
	}
	if len(warnings) != 1 {
		t.Fatalf("warned %d times, want 1: %v", len(warnings), warnings)
	}
	if !strings.Contains(warnings[0], "/mnt/remote/docker") {
		t.Errorf("warning does not name the data-root: %q", warnings[0])
	}

	// The data-root becomes measurable: the next fallback must warn again.
	if err := os.MkdirAll(filepath.Join(hostRoot, "mnt/remote/docker"), 0o755); err != nil {
		t.Fatal(err)
	}
	fs.stats[filepath.Join(hostRoot, "mnt/remote/docker")] = dataRootFS
	if r, err := reader.Read(context.Background()); err != nil || r.Source != "/mnt/remote/docker" {
		t.Fatalf("r=%+v err=%v, want the data-root reading", r, err)
	}
	delete(fs.stats, filepath.Join(hostRoot, "mnt/remote/docker"))
	if _, err := reader.Read(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(warnings) != 2 {
		t.Errorf("fallback after recovery was not re-announced: %v", warnings)
	}
}

func TestReader_NilDataRootResolverMeasuresHostRoot(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t)
	fs := &fakeFS{stats: map[string]Statfs{hostRoot: hostRootFS}}
	p := newProber(t, hostRoot, fs, mountinfo)
	reader := NewReader(p, nil, nil)

	r, err := reader.Read(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if r.Source != "/" {
		t.Errorf("Source=%q, want /", r.Source)
	}
}

// A persistent failure must not log every sampling interval, and recovery
// must be announced.
func TestReader_WarnsOnceUntilTheErrorChanges(t *testing.T) {
	hostRoot, mountinfo := newHostRoot(t)
	fs := &fakeFS{stats: map[string]Statfs{}}
	p := newProber(t, hostRoot, fs, mountinfoWithoutHostfs)

	var warnings []string
	reader := NewReader(p, nil, func(format string, args ...interface{}) {
		warnings = append(warnings, format)
	})

	for i := 0; i < 3; i++ {
		if _, err := reader.Read(context.Background()); err == nil {
			t.Fatal("expected failure")
		}
	}
	if len(warnings) != 1 {
		t.Fatalf("warned %d times for one unchanged failure, want 1: %v", len(warnings), warnings)
	}

	p.MountinfoPath = writeMountinfo(t, mountinfo)
	fs.stats[hostRoot] = hostRootFS
	if _, err := reader.Read(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(warnings) != 2 {
		t.Fatalf("recovery was not announced: %v", warnings)
	}
}

// --- wire struct ---

func TestReading_WireCarriesEveryField(t *testing.T) {
	r := Reading{Percent: 54.7, UsedBytes: 1, AvailableBytes: 2, TotalBytes: 4, Source: "/var/lib/docker"}
	w := r.Wire()
	if w.DiskPercent != 54.7 || w.DiskUsedBytes != 1 || w.DiskAvailableBytes != 2 || w.DiskTotalBytes != 4 || w.DiskSource != "/var/lib/docker" {
		t.Errorf("Wire()=%+v, want every Reading field copied", *w)
	}
}
