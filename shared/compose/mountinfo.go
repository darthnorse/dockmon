package compose

import (
	"bufio"
	"io"
	"os"
	"strconv"
	"strings"
)

// procMountInfoPath is the canonical location of mountinfo for the current
// process. Tests use discoverHostPathFromFile / discoverHostPathFromReader
// directly, so this never needs to be overridden.
const procMountInfoPath = "/proc/self/mountinfo"

// DiscoverHostPath returns the host-side source path that backs the given
// container-internal directory by consulting /proc/self/mountinfo. If no
// mount entry covers the path (DockMon is not containerized, or the path
// lives on overlay/tmpfs with no host backing), the input path is returned
// unchanged — that is the correct answer for a bare-metal install where
// container path equals host path.
//
// Returns an error only on unrecoverable read failures. A missing
// /proc/self/mountinfo (e.g., non-Linux host, /proc not mounted) is treated
// as "no match" and silently falls back to the input path.
func DiscoverHostPath(containerPath string) (string, error) {
	return discoverHostPathFromFile(procMountInfoPath, containerPath)
}

func discoverHostPathFromFile(path, containerPath string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return containerPath, nil
		}
		return containerPath, err
	}
	defer f.Close()
	return discoverHostPathFromReader(f, containerPath)
}

// discoverHostPathFromReader applies the discovery algorithm to an arbitrary
// reader.
func discoverHostPathFromReader(r io.Reader, containerPath string) (string, error) {
	type entry struct {
		root       string
		mountPoint string
	}

	// Track the longest mountPoint that is a path-prefix of containerPath.
	// On equal-length matches, the later entry wins, which mirrors how the
	// kernel resolves overlapping mounts at the same point.
	var best entry
	bestLen := -1

	scanner := bufio.NewScanner(r)
	// mountinfo lines can be long with many optional fields; bump the
	// default 64KB buffer to be safe.
	scanner.Buffer(make([]byte, 64*1024), 1024*1024)

	for scanner.Scan() {
		root, mountPoint, ok := parseMountInfoLine(scanner.Text())
		if !ok {
			continue
		}
		// Skip the root filesystem entry: matching it would rewrite any
		// containerPath to itself, producing a confusing no-op result and
		// masking the "no real bind covers this path" case.
		if mountPoint == "/" {
			continue
		}
		if !pathHasPrefix(containerPath, mountPoint) {
			continue
		}
		if len(mountPoint) >= bestLen {
			best = entry{root: root, mountPoint: mountPoint}
			bestLen = len(mountPoint)
		}
	}
	if err := scanner.Err(); err != nil {
		return containerPath, err
	}

	if bestLen < 0 {
		return containerPath, nil
	}

	suffix := containerPath[len(best.mountPoint):]
	return best.root + suffix, nil
}

// parseMountInfoLine extracts (root, mount_point) from one /proc/self/mountinfo
// line per proc(5). The format is:
//
//	mount_id parent_id major:minor root mount_point options [optional_fields]... - fs_type source super_options
//
// Optional fields are zero or more shared:N / master:N / propagate_from:N /
// unbindable tags; their list is terminated by a single "-" token followed
// by exactly three fields (fs_type, source, super_options). We validate the
// "-" token AND the trailing three fields so malformed lines fail closed
// rather than silently returning garbage.
func parseMountInfoLine(line string) (root, mountPoint string, ok bool) {
	fields := strings.Fields(line)
	if len(fields) < 10 {
		// Minimum: id parent maj:min root mountpoint opts - fstype source superopts
		return "", "", false
	}
	dashIdx := -1
	for i := 6; i < len(fields); i++ {
		if fields[i] == "-" {
			dashIdx = i
			break
		}
	}
	if dashIdx < 0 || len(fields)-dashIdx < 4 {
		// Need "-" plus at least three trailing fields.
		return "", "", false
	}
	root = unescapeOctal(fields[3])
	mountPoint = unescapeOctal(fields[4])
	return root, mountPoint, true
}

// unescapeOctal decodes the kernel's mountinfo path encoding. Per fs/seq_file.c,
// the kernel escapes ' ', '\t', '\n', and '\\' as \040, \011, \012, \134.
// Other bytes pass through unchanged. We accept any \NNN octal triplet to be
// permissive against future kernel additions.
func unescapeOctal(s string) string {
	var b strings.Builder
	b.Grow(len(s))
	for i := 0; i < len(s); i++ {
		// A backslash escape needs three octal digits after it. The triplet
		// occupies indices i+1..i+3, so we need i+4 <= len(s).
		if s[i] == '\\' && i+4 <= len(s) {
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

// pathHasPrefix reports whether p has prefix as a path-component prefix.
// "/app/data/stacks" has prefix "/app/data" but not "/app/dat".
// Both inputs must be cleaned absolute paths (no trailing slash except root).
func pathHasPrefix(p, prefix string) bool {
	if p == prefix {
		return true
	}
	if !strings.HasPrefix(p, prefix) {
		return false
	}
	// Boundary check: the char immediately after prefix must be '/'.
	// "/app/data" is a prefix of "/app/data/stacks" but not "/app/database".
	if prefix == "/" {
		return true
	}
	return p[len(prefix)] == '/'
}
