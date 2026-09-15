// Package hostdisk measures a host filesystem's capacity from inside or
// outside a container, failing closed whenever the reading could be the
// container's own disk rather than the host's.
package hostdisk

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
)

// DefaultHostRoot is where a containerized process expects the host root
// bind-mounted (`-v /:/hostfs:ro`).
const DefaultHostRoot = "/hostfs"

const defaultMountinfoPath = "/proc/self/mountinfo"

var (
	// ErrHostRootNotMounted means the host root directory exists (or not) but
	// is not a mount point, so Statfs there would measure the container's own
	// filesystem and report it as the host's.
	ErrHostRootNotMounted = errors.New("host root is not a mount point")
	// ErrInvalidStatfs marks a statfs result whose counters cannot describe a
	// real filesystem; computing from them would yield a plausible wrong number.
	ErrInvalidStatfs = errors.New("inconsistent statfs counters")
)

// Statfs is the subset of statfs(2) the formula needs. Block counts are in
// fragment-size units, as the kernel defines them.
type Statfs struct {
	Blocks uint64 // total data blocks
	Bfree  uint64 // free blocks, including root-reserved ones
	Bavail uint64 // free blocks available to an unprivileged writer
	Bsize  uint64
	Frsize uint64
}

// Reading is one capacity measurement. Percent follows df's Use%:
// used / (used + available), so root-reserved blocks count as full from a
// non-root writer's point of view. UsedBytes and AvailableBytes regenerate
// Percent exactly; TotalBytes is the true filesystem size and is larger than
// their sum on a filesystem with reserved blocks.
type Reading struct {
	Percent        float64
	UsedBytes      uint64
	AvailableBytes uint64
	TotalBytes     uint64
	// Source is the logical host path measured ("/var/lib/docker" or "/"),
	// never the container-private probe path.
	Source string
}

// Compute derives a Reading from raw statfs counters.
func Compute(s Statfs) (Reading, error) {
	unit := s.Frsize
	if unit == 0 {
		unit = s.Bsize
	}
	switch {
	case unit == 0:
		return Reading{}, fmt.Errorf("%w: zero block size", ErrInvalidStatfs)
	case s.Blocks == 0:
		return Reading{}, fmt.Errorf("%w: zero blocks", ErrInvalidStatfs)
	case s.Bfree > s.Blocks:
		return Reading{}, fmt.Errorf("%w: free %d exceeds total %d", ErrInvalidStatfs, s.Bfree, s.Blocks)
	case s.Bavail > s.Bfree:
		return Reading{}, fmt.Errorf("%w: available %d exceeds free %d", ErrInvalidStatfs, s.Bavail, s.Bfree)
	case s.Blocks > math.MaxUint64/unit:
		return Reading{}, fmt.Errorf("%w: %d blocks of %d bytes overflow", ErrInvalidStatfs, s.Blocks, unit)
	}

	usedBlocks := s.Blocks - s.Bfree
	denominator := usedBlocks + s.Bavail
	if denominator == 0 {
		return Reading{}, fmt.Errorf("%w: no space usable by a non-root writer", ErrInvalidStatfs)
	}

	pct := float64(usedBlocks) / float64(denominator) * 100
	return Reading{
		Percent:        math.Min(100, math.Max(0, pct)),
		UsedBytes:      usedBlocks * unit,
		AvailableBytes: s.Bavail * unit,
		TotalBytes:     s.Blocks * unit,
	}, nil
}

// Prober measures filesystems under a host root. HostRoot is "" when the
// process runs on the host itself and paths are used as-is.
type Prober struct {
	HostRoot      string
	Statfs        func(path string) (Statfs, error)
	MountinfoPath string
}

// NewProber returns a Prober using the real statfs(2) and /proc/self/mountinfo.
func NewProber(hostRoot string) *Prober {
	return &Prober{
		HostRoot:      hostRoot,
		Statfs:        statfs,
		MountinfoPath: defaultMountinfoPath,
	}
}

// HostRootMounted reports whether HostRoot is a real mount point. Always true
// when HostRoot is empty. A bare directory at HostRoot makes Statfs succeed
// against the container's own filesystem, so existence alone proves nothing.
func (p *Prober) HostRootMounted() (bool, error) {
	if p.HostRoot == "" {
		return true, nil
	}
	return isMountPoint(p.MountinfoPath, p.HostRoot)
}

// Probe measures the filesystem holding dataRoot (Docker's data-root, an
// absolute host path), falling back to the host root when dataRoot is empty,
// relative, absent under the host view, or unreadable. Reading.Source says
// which was measured.
func (p *Prober) Probe(dataRoot string) (Reading, error) {
	mounted, err := p.HostRootMounted()
	if err != nil {
		return Reading{}, fmt.Errorf("verify %s mount: %w", p.HostRoot, err)
	}
	if !mounted {
		return Reading{}, fmt.Errorf("%w: %s", ErrHostRootNotMounted, p.HostRoot)
	}

	if dataRoot != "" && filepath.IsAbs(dataRoot) {
		if r, err := p.measure(filepath.Join(p.HostRoot, dataRoot)); err == nil {
			r.Source = filepath.Clean(dataRoot)
			return r, nil
		}
	}

	rootPath := p.HostRoot
	if rootPath == "" {
		rootPath = "/"
	}
	r, err := p.measure(rootPath)
	if err != nil {
		return Reading{}, err
	}
	r.Source = "/"
	return r, nil
}

func (p *Prober) measure(path string) (Reading, error) {
	st, err := p.Statfs(path)
	if err != nil {
		return Reading{}, fmt.Errorf("statfs %s: %w", path, err)
	}
	r, err := Compute(st)
	if err != nil {
		return Reading{}, fmt.Errorf("%s: %w", path, err)
	}
	return r, nil
}

// isMountPoint scans mountinfo for an entry whose mount point is exactly
// mountPoint. Field 5 carries octal escapes for whitespace and backslashes.
func isMountPoint(mountinfoPath, mountPoint string) (bool, error) {
	f, err := os.Open(mountinfoPath)
	if err != nil {
		return false, err
	}
	defer f.Close()

	want := filepath.Clean(mountPoint)
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) < 5 {
			continue
		}
		if filepath.Clean(unescapeMountinfo(fields[4])) == want {
			return true, nil
		}
	}
	return false, scanner.Err()
}

func unescapeMountinfo(s string) string {
	if !strings.Contains(s, `\`) {
		return s
	}
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] == '\\' && i+3 < len(s) {
			if v, err := strconv.ParseUint(s[i+1:i+4], 8, 8); err == nil {
				b.WriteByte(byte(v))
				i += 3
				continue
			}
		}
		b.WriteByte(s[i])
	}
	return b.String()
}

// Reader probes on every Read, resolving Docker's data-root once via
// DataRoot and measuring the host root until that succeeds. Warnf, when set,
// is called once when the failure text changes and once on recovery, so a
// persistent failure does not log every sampling interval.
type Reader struct {
	prober   *Prober
	dataRoot func(context.Context) (string, error)
	warnf    func(format string, args ...interface{})

	mu           sync.Mutex
	resolvedRoot string
	resolved     bool
	lastErr      string
}

// NewReader wires a Prober to an optional data-root resolver and logger.
func NewReader(p *Prober, dataRoot func(context.Context) (string, error), warnf func(string, ...interface{})) *Reader {
	return &Reader{prober: p, dataRoot: dataRoot, warnf: warnf}
}

// Read returns the current reading, or an error when nothing trustworthy
// could be measured. Callers must send no disk fields on error.
func (r *Reader) Read(ctx context.Context) (*Reading, error) {
	r.mu.Lock()
	defer r.mu.Unlock()

	if !r.resolved && r.dataRoot != nil {
		if root, err := r.dataRoot(ctx); err == nil {
			r.resolvedRoot = root
			r.resolved = true
		}
	}

	reading, err := r.prober.Probe(r.resolvedRoot)
	if err != nil {
		if msg := err.Error(); msg != r.lastErr {
			r.lastErr = msg
			r.warn("Host disk usage unavailable: %v", err)
		}
		return nil, err
	}
	if r.lastErr != "" {
		r.lastErr = ""
		r.warn("Host disk usage available again (measuring %s)", reading.Source)
	}
	return &reading, nil
}

func (r *Reader) warn(format string, args ...interface{}) {
	if r.warnf != nil {
		r.warnf(format, args...)
	}
}
